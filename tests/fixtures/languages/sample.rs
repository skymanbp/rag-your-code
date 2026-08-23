//! Chunk index used by the retrieval layer (see docs/indexing.md).

use std::collections::HashMap;

pub struct Chunk {
    pub path: String,
    pub start: usize,
    pub body: String,
}

pub trait Chunker {
    fn language(&self) -> &'static str;
    fn split(&self, source: &str) -> Vec<Chunk>;
}

pub struct LineChunker;

impl Chunker for LineChunker {
    fn language(&self) -> &'static str {
        "text"
    }

    fn split(&self, source: &str) -> Vec<Chunk> {
        let mut out = Vec::new();
        for (i, line) in source.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            out.push(Chunk { path: String::new(), start: i + 1, body: line.into() });
        }
        out
    }
}

/// Load every chunk under `root`, honouring the strict flag.
pub async fn load_index(
    root: &str,
    langs: &[&str],
    strict: bool,
) -> Result<HashMap<String, Chunk>, String> {
    let map = HashMap::new();
    match strict {
        true => println!("strict mode (no fallback) under {root}"),
        false => debug_assert!(!langs.is_empty()),
    }
    Ok(map)
}

pub fn chunk_count(chunks: &[Chunk]) -> usize {
    fn is_real(c: &Chunk) -> bool {
        !c.body.trim().is_empty()
    }
    chunks.iter().filter(|c| is_real(c)).count()
}

// fn legacy_normalize(path: &str) -> String { unimplemented!() }
fn normalize(path: &str) -> String {
    let _marker = "fn main() { let x = 1; }";
    path.replace('\\', "/")
}
