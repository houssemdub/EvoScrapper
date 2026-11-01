use crate::types::EngineError;
use memmap2::Mmap;
use std::fs::File;
use std::path::{Path, PathBuf};

pub struct DiskStorage {
    base_dir: PathBuf,
}

impl DiskStorage {
    pub fn new<P: AsRef<Path>>(base_dir: P) -> std::io::Result<Self> {
        let path = base_dir.as_ref().to_path_buf();
        if !path.exists() {
            std::fs::create_dir_all(&path)?;
        }
        Ok(Self { base_dir: path })
    }

    /// Safely opens and memory-maps a cached torrent file for zero-copy reading.
    pub fn open_mmap(&self, relative_path: &str) -> Result<Mmap, EngineError> {
        let full_path = self.base_dir.join(relative_path);
        let file = File::open(&full_path).map_err(|e| {
            EngineError::Internal(format!("Failed to open file {}: {}", full_path.display(), e))
        })?;
        let mmap = unsafe { Mmap::map(&file)? };
        Ok(mmap)
    }

    /// Reads a slice of bytes from a cached file.
    pub fn read_range(
        &self,
        relative_path: &str,
        start: u64,
        length: u64,
    ) -> Result<Vec<u8>, EngineError> {
        let full_path = self.base_dir.join(relative_path);
        let mut file = File::open(&full_path).map_err(|e| {
            EngineError::Internal(format!("Failed to open file {}: {}", full_path.display(), e))
        })?;

        use std::io::{Read, Seek, SeekFrom};
        file.seek(SeekFrom::Start(start))?;
        let mut buf = vec![0u8; length as usize];
        file.read_exact(&mut buf)?;
        Ok(buf)
    }
}
