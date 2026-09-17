//! Physical prefix comparison only. The recovery caller must genuinely replay
//! both archives before calling, then check both complete byte digests again.
//! No pathname is reopened, file is written, or authenticated state is returned.
use super::{
    read_at, regular, ActiveJournal, File, PoolError, COPY_CHUNK, MAX_SEGMENTS, SEGMENT_BYTES,
};
use std::io;

// Fill each side independently: two legitimate short reads need not return the
// same size. Explicit offsets also avoid cloned Windows handles' shared cursor.
fn fill_at(
    mut bytes: &mut [u8],
    mut offset: u64,
    mut read: impl FnMut(&mut [u8], u64) -> io::Result<usize>,
) -> Result<(), PoolError> {
    while !bytes.is_empty() {
        match read(bytes, offset) {
            Ok(0) => return Err(PoolError::Corrupt),
            Ok(count) => {
                if count > bytes.len() {
                    return Err(PoolError::Corrupt);
                }
                offset = offset
                    .checked_add(u64::try_from(count).map_err(|_| PoolError::Bounds)?)
                    .ok_or(PoolError::Bounds)?;
                bytes = &mut bytes[count..];
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    Ok(())
}

fn exact_file_end(file: &File, length: u64) -> Result<(), PoolError> {
    let mut extra = [0];
    loop {
        match read_at(file, &mut extra, length) {
            Ok(0) => break,
            Ok(_) => return Err(PoolError::Corrupt),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(PoolError::Storage),
        }
    }
    let metadata = file.metadata().map_err(|_| PoolError::Storage)?;
    if !regular(&metadata) || metadata.len() != length {
        return Err(PoolError::Corrupt);
    }
    Ok(())
}

fn compare_prefix(
    base: &File,
    base_length: u64,
    later: &File,
    later_length: u64,
    mismatch: PoolError,
) -> Result<(), PoolError> {
    if base_length > later_length {
        return Err(mismatch);
    }
    let mut left = [0; COPY_CHUNK];
    let mut right = [0; COPY_CHUNK];
    let mut offset = 0;
    while offset < base_length {
        let remaining = base_length.checked_sub(offset).ok_or(PoolError::Bounds)?;
        let take = usize::try_from(
            remaining.min(u64::try_from(COPY_CHUNK).map_err(|_| PoolError::Bounds)?),
        )
        .map_err(|_| PoolError::Bounds)?;
        fill_at(&mut left[..take], offset, |bytes, position| {
            read_at(base, bytes, position)
        })?;
        fill_at(&mut right[..take], offset, |bytes, position| {
            read_at(later, bytes, position)
        })?;
        if left[..take] != right[..take] {
            return Err(mismatch);
        }
        offset = offset
            .checked_add(u64::try_from(take).map_err(|_| PoolError::Bounds)?)
            .ok_or(PoolError::Bounds)?;
    }
    // The base prefix must be its whole physical file. The later suffix is
    // covered by its full replay and the recovery caller's final layout hash.
    exact_file_end(base, base_length)?;
    exact_file_end(later, later_length)
}

fn emit_range(
    consume: &mut impl FnMut(u32, u32, u32) -> Result<(), PoolError>,
    appended: &mut u64,
    index: usize,
    offset: u64,
    length: u64,
) -> Result<(), PoolError> {
    if index >= MAX_SEGMENTS
        || length == 0
        || offset.checked_add(length).ok_or(PoolError::Bounds)? > SEGMENT_BYTES
    {
        return Err(PoolError::Bounds);
    }
    *appended = appended.checked_add(length).ok_or(PoolError::Bounds)?;
    consume(
        u32::try_from(index).map_err(|_| PoolError::Bounds)?,
        u32::try_from(offset).map_err(|_| PoolError::Bounds)?,
        u32::try_from(length).map_err(|_| PoolError::Bounds)?,
    )
}

impl ActiveJournal {
    /// Visit only the old tail's suffix and consecutive whole new segments.
    /// The private callback's partial work must never escape on an error. The
    /// returned count includes only completely unchanged existing journal files.
    pub(in crate::pool) fn visit_append_ranges(
        &self,
        genesis: &File,
        later: &Self,
        later_genesis: &File,
        mut consume: impl FnMut(u32, u32, u32) -> Result<(), PoolError>,
    ) -> Result<u32, PoolError> {
        self.check(genesis)?;
        later.check(later_genesis)?;
        if self.header_length != later.header_length {
            return Err(PoolError::Genesis);
        }
        if self.segments.len() > later.segments.len() || self.length > later.length {
            return Err(PoolError::Stale);
        }
        compare_prefix(
            genesis,
            self.header_length,
            later_genesis,
            later.header_length,
            PoolError::Genesis,
        )?;
        let mut unchanged = 0u32;
        for (index, base) in self.segments.iter().enumerate() {
            let next = later.segments.get(index).ok_or(PoolError::Stale)?;
            let is_tail = index.checked_add(1).ok_or(PoolError::Bounds)? == self.segments.len();
            if (is_tail && next.length < base.length) || (!is_tail && next.length != base.length) {
                return Err(PoolError::Stale);
            }
            compare_prefix(
                &base.file,
                base.length,
                &next.file,
                next.length,
                PoolError::Stale,
            )?;
            if next.length == base.length {
                unchanged = unchanged.checked_add(1).ok_or(PoolError::Bounds)?;
            }
        }
        let mut appended = 0;
        if let Some(base) = self.segments.last() {
            let index = self.segments.len().checked_sub(1).ok_or(PoolError::Bounds)?;
            let next = later.segments.get(index).ok_or(PoolError::Stale)?;
            let length = next.length.checked_sub(base.length).ok_or(PoolError::Stale)?;
            if length != 0 {
                emit_range(&mut consume, &mut appended, index, base.length, length)?;
            }
        }
        for (index, segment) in later.segments.iter().enumerate().skip(self.segments.len()) {
            emit_range(&mut consume, &mut appended, index, 0, segment.length)?;
        }
        if self.length.checked_add(appended).ok_or(PoolError::Bounds)? != later.length {
            return Err(PoolError::Corrupt);
        }
        self.check(genesis)?;
        later.check(later_genesis)?;
        Ok(unchanged)
    }
}

#[cfg(test)]
mod tests;
