use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    None = 0,
    Lookahead = 1,
    Buffer = 2,
    Critical = 3,
}

#[derive(Clone, Debug)]
pub struct PieceSchedule {
    pub file_start_piece: usize,
    pub file_end_piece: usize,
    pub urgent_ranges: Vec<(usize, usize)>,
    pub buffer_ranges: Vec<(usize, usize)>,
    pub drop_end_piece: Option<usize>,
}

#[derive(Clone, Debug)]
pub struct BlockRequest {
    pub piece_idx: usize,
    pub block_offset: u32,
    pub peer_id: String,
    pub requested_at: Instant,
    pub wire_speed_bps: u64,
}

pub struct PiecePicker {
    pub piece_length: usize,
    pub total_pieces: usize,
    pub active_readers: HashMap<String, u64>, // reader_id -> byte_offset
    pub active_requests: HashMap<(usize, u32), BlockRequest>,
    pub retention_pieces: usize,
    pub stall_timeout: Duration,
}

impl PiecePicker {
    pub fn new(piece_length: usize, total_pieces: usize) -> Self {
        Self {
            piece_length: piece_length.max(16384),
            total_pieces,
            active_readers: HashMap::new(),
            active_requests: HashMap::new(),
            retention_pieces: 10,
            stall_timeout: Duration::from_millis(2500),
        }
    }

    pub fn byte_to_piece(&self, byte_offset: u64) -> usize {
        (byte_offset / self.piece_length as u64) as usize
    }

    /// Computes the 3-tier piece prioritization window.
    pub fn compute_schedule(
        &self,
        file_start_byte: u64,
        file_length: u64,
        cursor_byte: u64,
        estimated_bytes_per_sec: u64,
    ) -> PieceSchedule {
        let file_start_piece = self.byte_to_piece(file_start_byte);
        let file_end_piece = self.byte_to_piece(file_start_byte + file_length.saturating_sub(1));
        let cursor_piece = self.byte_to_piece(cursor_byte).clamp(file_start_piece, file_end_piece);

        let bps = estimated_bytes_per_sec.max(2_000_000); // Default 2MB/s (~16Mbps video)

        // 1. Urgent Head Pieces: First 10MB of the file (or EBML/ftyp header)
        let head_bytes = 10 * 1024 * 1024;
        let head_pieces = (head_bytes / self.piece_length).max(4);
        let head_end = (file_start_piece + head_pieces).min(file_end_piece);

        // 2. Urgent Tail Pieces: Last 4MB of the file (MP4 moov atom / index)
        let tail_bytes = 4 * 1024 * 1024;
        let tail_pieces = (tail_bytes / self.piece_length).max(2);
        let tail_start = file_end_piece.saturating_sub(tail_pieces).max(file_start_piece);

        // 3. Sliding Playback Window (Current cursor + 20s urgent, +60s buffer)
        let urgent_playback_pieces = ((20 * bps) as usize / self.piece_length).clamp(4, 48);
        let urgent_playback_end = (cursor_piece + urgent_playback_pieces).min(file_end_piece);

        let buffer_pieces = ((60 * bps) as usize / self.piece_length).clamp(8, 128);
        let buffer_end = (urgent_playback_end + buffer_pieces).min(file_end_piece);

        let mut urgent_ranges = Vec::new();
        // Head range
        urgent_ranges.push((file_start_piece, head_end));
        // Cursor urgent range
        urgent_ranges.push((cursor_piece, urgent_playback_end));
        // Tail range
        if tail_start <= file_end_piece {
            urgent_ranges.push((tail_start, file_end_piece));
        }

        let mut buffer_ranges = Vec::new();
        if urgent_playback_end < buffer_end {
            buffer_ranges.push((urgent_playback_end + 1, buffer_end));
        }

        // Retention drop: Pieces behind cursor - retention_pieces
        let drop_end_piece = if cursor_piece > file_start_piece + self.retention_pieces {
            Some(cursor_piece - self.retention_pieces)
        } else {
            None
        };

        PieceSchedule {
            file_start_piece,
            file_end_piece,
            urgent_ranges,
            buffer_ranges,
            drop_end_piece,
        }
    }

    /// Evaluates in-flight requests and identifies stalled blocks on slow wires.
    pub fn scan_stalled_requests(&self, now: Instant) -> Vec<(usize, u32, String)> {
        let mut cancelled = Vec::new();
        for ((piece_idx, block_offset), req) in &self.active_requests {
            if now.duration_since(req.requested_at) > self.stall_timeout
                && req.wire_speed_bps < 1024
            {
                cancelled.push((*piece_idx, *block_offset, req.peer_id.clone()));
            }
        }
        cancelled
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_schedule_head_tail_and_sliding_window() {
        let piece_len = 1024 * 1024; // 1MB pieces
        let total_pieces = 2000;      // 2GB file
        let picker = PiecePicker::new(piece_len, total_pieces);

        // File spans 0..2000 pieces, cursor at 0
        let sched = picker.compute_schedule(0, 2000 * 1024 * 1024, 0, 2_000_000);

        assert_eq!(sched.file_start_piece, 0);
        assert_eq!(sched.file_end_piece, 1999);
        assert!(sched.drop_end_piece.is_none());

        // Head must be urgent (at least 10MB = 10 pieces)
        assert!(sched.urgent_ranges.iter().any(|(s, e)| *s == 0 && *e >= 9));
        // Tail must be urgent (last 4MB = pieces 1996..1999)
        assert!(sched.urgent_ranges.iter().any(|(s, e)| *e == 1999 && *s <= 1997));

        // When seeking to piece 500 (500MB):
        let seek_sched = picker.compute_schedule(
            0,
            2000 * 1024 * 1024,
            500 * 1024 * 1024,
            2_000_000,
        );
        // Deselect behind retention window (500 - 10 = 490)
        assert_eq!(seek_sched.drop_end_piece, Some(490));
        // Urgent window must cover piece 500 onwards
        assert!(seek_sched.urgent_ranges.iter().any(|(s, e)| *s <= 500 && *e > 500));
    }
}
