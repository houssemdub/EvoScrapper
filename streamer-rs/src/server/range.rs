use crate::types::EngineError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ByteRange {
    pub start: u64,
    pub end: u64,
    pub total: u64,
}

impl ByteRange {
    pub fn length(&self) -> u64 {
        if self.end >= self.start {
            self.end - self.start + 1
        } else {
            0
        }
    }

    pub fn content_range_header(&self) -> String {
        format!("bytes {}-{}/{}", self.start, self.end, self.total)
    }
}

pub fn parse_range_header(header_val: &str, total_size: u64) -> Result<ByteRange, EngineError> {
    if total_size == 0 {
        return Err(EngineError::InvalidRange("Total file size is zero".into()));
    }

    let trimmed = header_val.trim();
    if !trimmed.starts_with("bytes=") {
        return Err(EngineError::InvalidRange("Header must start with 'bytes='".into()));
    }

    let range_str = &trimmed[6..].trim();
    // Only support single range
    if range_str.contains(',') {
        return Err(EngineError::InvalidRange("Multi-range not supported".into()));
    }

    let parts: Vec<&str> = range_str.split('-').collect();
    if parts.len() != 2 {
        return Err(EngineError::InvalidRange("Malformed range specifier".into()));
    }

    let start_str = parts[0].trim();
    let end_str = parts[1].trim();

    if start_str.is_empty() && end_str.is_empty() {
        return Err(EngineError::InvalidRange("Empty range bounds".into()));
    }

    if start_str.is_empty() {
        // Suffix range: bytes=-500 (last 500 bytes)
        let suffix_len: u64 = end_str
            .parse()
            .map_err(|_| EngineError::InvalidRange("Invalid suffix length".into()))?;
        if suffix_len == 0 {
            return Err(EngineError::InvalidRange("Zero suffix length".into()));
        }
        let actual_len = std::cmp::min(suffix_len, total_size);
        let start = total_size - actual_len;
        let end = total_size - 1;
        Ok(ByteRange { start, end, total: total_size })
    } else {
        let start: u64 = start_str
            .parse()
            .map_err(|_| EngineError::InvalidRange("Invalid start offset".into()))?;
        if start >= total_size {
            return Err(EngineError::InvalidRange(format!(
                "Start offset {} >= total size {}",
                start, total_size
            )));
        }

        let end = if end_str.is_empty() {
            total_size - 1
        } else {
            let requested_end: u64 = end_str
                .parse()
                .map_err(|_| EngineError::InvalidRange("Invalid end offset".into()))?;
            std::cmp::min(requested_end, total_size - 1)
        };

        if start > end {
            return Err(EngineError::InvalidRange("Start offset cannot exceed end".into()));
        }

        Ok(ByteRange { start, end, total: total_size })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_ranges() {
        let total = 1000u64;

        // bytes=0-499
        let r1 = parse_range_header("bytes=0-499", total).unwrap();
        assert_eq!(r1.start, 0);
        assert_eq!(r1.end, 499);
        assert_eq!(r1.length(), 500);
        assert_eq!(r1.content_range_header(), "bytes 0-499/1000");

        // bytes=500- (to end of file)
        let r2 = parse_range_header("bytes=500-", total).unwrap();
        assert_eq!(r2.start, 500);
        assert_eq!(r2.end, 999);
        assert_eq!(r2.length(), 500);

        // bytes=-200 (last 200 bytes)
        let r3 = parse_range_header("bytes=-200", total).unwrap();
        assert_eq!(r3.start, 800);
        assert_eq!(r3.end, 999);
        assert_eq!(r3.length(), 200);

        // Clamped overflow: bytes=800-2000
        let r4 = parse_range_header("bytes=800-2000", total).unwrap();
        assert_eq!(r4.start, 800);
        assert_eq!(r4.end, 999);
        assert_eq!(r4.length(), 200);
    }

    #[test]
    fn test_invalid_ranges() {
        let total = 1000u64;
        assert!(parse_range_header("bytes=1000-", total).is_err());
        assert!(parse_range_header("bytes=500-400", total).is_err());
        assert!(parse_range_header("bytes=0-100,200-300", total).is_err());
        assert!(parse_range_header("not-a-range", total).is_err());
    }
}
