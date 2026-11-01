use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};

type HmacSha256 = Hmac<Sha256>;

pub const MAX_SIGNED_URL_TTL_SECONDS: u64 = 24 * 60 * 60;

/// Constant-time slice comparison to prevent timing attacks.
pub fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// Computes HMAC-SHA256 signature for signed URL expiration timestamp.
pub fn sign_expiry(expires: u64, secret: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .expect("HMAC can take key of any size");
    mac.update(expires.to_string().as_bytes());
    let result = mac.finalize();
    hex::encode(result.into_bytes())
}

/// Verifies whether the header token matches the daemon secret.
pub fn validate_header_token(
    supplied: Option<&str>,
    secret: &str,
    allow_anonymous: bool,
) -> bool {
    if allow_anonymous {
        return true;
    }
    match supplied {
        Some(token) if !token.trim().is_empty() && !secret.is_empty() => {
            constant_time_eq(token.trim().as_bytes(), secret.as_bytes())
        }
        _ => false,
    }
}

/// Verifies URL signature (`expires` and `sig` query parameters).
pub fn validate_stream_signature(
    expires_str: Option<&str>,
    sig_str: Option<&str>,
    secret: &str,
    allow_anonymous: bool,
) -> bool {
    if allow_anonymous {
        return true;
    }
    let (expires_str, sig) = match (expires_str, sig_str) {
        (Some(e), Some(s)) => (e, s),
        _ => return false,
    };

    let expires = match expires_str.parse::<u64>() {
        Ok(exp) if exp > 0 => exp,
        _ => return false,
    };

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    if expires < now || expires > now + MAX_SIGNED_URL_TTL_SECONDS {
        return false;
    }

    let expected_sig = sign_expiry(expires, secret);
    constant_time_eq(sig.as_bytes(), expected_sig.as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sign_and_validate_stream_signature() {
        let secret = "super-secret-token-key-123456";
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let expires = now + 1800;

        let sig = sign_expiry(expires, secret);
        assert!(!sig.is_empty());

        let valid = validate_stream_signature(
            Some(&expires.to_string()),
            Some(&sig),
            secret,
            false,
        );
        assert!(valid);

        // Invalid signature
        let invalid = validate_stream_signature(
            Some(&expires.to_string()),
            Some("badsignature123"),
            secret,
            false,
        );
        assert!(!invalid);

        // Expired timestamp
        let expired = now.saturating_sub(10);
        let expired_sig = sign_expiry(expired, secret);
        let valid_expired = validate_stream_signature(
            Some(&expired.to_string()),
            Some(&expired_sig),
            secret,
            false,
        );
        assert!(!valid_expired);
    }

    #[test]
    fn test_header_token_validation() {
        let secret = "evo-daemon-token-abc";
        assert!(validate_header_token(Some("evo-daemon-token-abc"), secret, false));
        assert!(!validate_header_token(Some("wrong-token"), secret, false));
        assert!(!validate_header_token(None, secret, false));
        assert!(validate_header_token(None, secret, true));
    }
}
