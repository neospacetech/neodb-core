//! Indexing system for NeoDB storage engine

use std::collections::HashMap;
use serde::{Serialize, Deserialize};
use crate::{Result, StorageError};

/// Index configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexConfig {
    pub name: String,
    pub unique: bool,
    pub btree_order: usize,
}

/// Simple in-memory index implementation
/// TODO: Replace with persistent B-tree or LSM-tree based index
#[derive(Debug)]
pub struct Index {
    config: IndexConfig,
    // TODO: Replace HashMap with persistent index structure
    data: HashMap<String, Vec<String>>, // key -> list of record IDs
}

impl Index {
    pub fn new(config: IndexConfig) -> Self {
        Self {
            config,
            data: HashMap::new(),
        }
    }

    pub async fn insert(&mut self, key: String, record_id: String) -> Result<()> {
        if self.config.unique && self.data.contains_key(&key) {
            return Err(StorageError::Index(format!("Duplicate key in unique index: {}", key)));
        }

        self.data
            .entry(key)
            .or_insert_with(Vec::new)
            .push(record_id);
        
        Ok(())
    }

    pub async fn get(&self, key: &str) -> Result<Vec<String>> {
        Ok(self.data.get(key).cloned().unwrap_or_default())
    }

    pub async fn remove(&mut self, key: &str, record_id: &str) -> Result<bool> {
        if let Some(records) = self.data.get_mut(key) {
            if let Some(pos) = records.iter().position(|x| x == record_id) {
                records.remove(pos);
                if records.is_empty() {
                    self.data.remove(key);
                }
                return Ok(true);
            }
        }
        Ok(false)
    }
}