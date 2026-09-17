//! Bind an archive's names to its retained handles. File locks protect handles,
//! not Unix directory entries: an old unlinked handle can still contain valid
//! bytes after its pathname has been replaced. Do not certify that new pathname.
//!
//! Unix compares (device, inode). Windows retains handles without DELETE sharing
//! for this directory and every archive file. No unsafe APIs, nightly file IDs,
//! new dependency, or widening of the live journal's access rights is involved.
//! Trusted parents/OS/filesystem remain required; this is not a TOCTOU sandbox.
use super::{regular, File, OpenOptions, Path, PoolError};
use std::fs::{self, Metadata};

pub(in crate::pool) struct Directory {
    file: File,
}

fn real_directory(meta: &Metadata) -> bool {
    if !meta.is_dir() || meta.file_type().is_symlink() {
        return false;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if meta.file_attributes() & 0x400 != 0 {
            return false;
        }
    }
    true
}

fn same_object(named: &Metadata, opened: &Metadata) -> Result<(), PoolError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if named.dev() != opened.dev() || named.ino() != opened.ino() {
            return Err(PoolError::Corrupt);
        }
    }
    #[cfg(windows)]
    {
        // Stable std does not expose Windows file IDs. Retaining no-delete-share
        // handles prevents ordinary rename/replacement while they remain open.
        // Never use equal size/timestamps as if they were unique file identity.
        let _ = (named, opened);
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (named, opened);
        Err(PoolError::Unavailable)
    }
    #[cfg(any(unix, windows))]
    Ok(())
}

/// Read/write sharing preserves the existing lock tests and simultaneous readers;
/// excluding DELETE sharing also denies rename on Windows. Reparse points are
/// opened as such so the caller's metadata check can reject, not follow, them.
pub(in crate::pool) fn retain_name(options: &mut OpenOptions) {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const SHARE_READ_WRITE: u32 = 0x1 | 0x2;
        const OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        options
            .share_mode(SHARE_READ_WRITE)
            .custom_flags(OPEN_REPARSE_POINT);
    }
    #[cfg(not(windows))]
    let _ = options;
}

impl Directory {
    pub(in crate::pool) fn open(path: &Path) -> Result<Self, PoolError> {
        if !path.is_absolute() {
            return Err(PoolError::Bounds);
        }
        let before = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        if !real_directory(&before) {
            return Err(PoolError::Bounds);
        }
        let mut options = OpenOptions::new();
        options.read(true);
        retain_name(&mut options);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            const BACKUP_SEMANTICS: u32 = 0x0200_0000;
            const OPEN_REPARSE_POINT: u32 = 0x0020_0000;
            // custom_flags replaces flags, so retain OPEN_REPARSE_POINT here.
            options.custom_flags(BACKUP_SEMANTICS | OPEN_REPARSE_POINT);
        }
        let file = options.open(path).map_err(|_| PoolError::Storage)?;
        let opened = file.metadata().map_err(|_| PoolError::Storage)?;
        if !real_directory(&opened) {
            return Err(PoolError::Corrupt);
        }
        same_object(&before, &opened)?;
        let retained = Self { file };
        retained.check(path)?;
        Ok(retained)
    }

    pub(in crate::pool) fn check(&self, path: &Path) -> Result<(), PoolError> {
        let named = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
        let opened = self.file.metadata().map_err(|_| PoolError::Storage)?;
        if !real_directory(&named) || !real_directory(&opened) {
            return Err(PoolError::Corrupt);
        }
        same_object(&named, &opened)
    }

    pub(in crate::pool) fn try_clone(&self) -> Result<Self, PoolError> {
        Ok(Self {
            file: self.file.try_clone().map_err(|_| PoolError::Storage)?,
        })
    }

    /// Persist directory entries on Unix. Stable std has no corresponding
    /// portable Windows guarantee; process-failure tests are not power-loss tests.
    pub(in crate::pool) fn sync(&self) -> Result<(), PoolError> {
        #[cfg(unix)]
        self.file.sync_all().map_err(|_| PoolError::Storage)?;
        Ok(())
    }
}

pub(in crate::pool) fn check_file(path: &Path, file: &File, length: u64) -> Result<(), PoolError> {
    let named = fs::symlink_metadata(path).map_err(|_| PoolError::Storage)?;
    let opened = file.metadata().map_err(|_| PoolError::Storage)?;
    if !regular(&named) || !regular(&opened) || named.len() != length || opened.len() != length {
        return Err(PoolError::Corrupt);
    }
    same_object(&named, &opened)
}
