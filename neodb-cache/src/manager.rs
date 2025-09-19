//! Cache manager for coordinating different cache layers
//!
//! Provides a unified interface for managing multiple cache types
//! and implementing cache hierarchies.

use std::sync::Arc;
use dashmap::DashMap;
use serde::{Serialize, Deserialize};
use crate::{Result, CacheError};

/// Configuration for the cache manager
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheConfig {
    pub l1_size: usize,
    pub l2_size: usize,
    pub ttl_seconds: Option<u64>,
    pub enable_compression: bool,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            l1_size: 1000,
            l2_size: 10000,
            ttl_seconds: Some(3600), // 1 hour
            enable_compression: false,
        }
    }
}

/// Cache manager coordinating multiple cache layers
///
/// Implements a hierarchical caching strategy with L1 (hot data)
/// and L2 (warm data) caches for optimal performance.
#[derive(Debug)]
pub struct CacheManager {
    config: CacheConfig,
    l1_cache: Arc<DashMap<String, CacheEntry>>,
    l2_cache: Arc<DashMap<String, CacheEntry>>,
    stats: CacheStats,
}

/// Cache entry with metadata
#[derive(Debug, Clone)]
struct CacheEntry {
    data: Vec<u8>,
    created_at: std::time::Instant,
    access_count: u64,
    last_accessed: std::time::Instant,
}

impl CacheEntry {
    fn new(data: Vec<u8>) -> Self {
        let now = std::time::Instant::now();
        Self {
            data,
            created_at: now,
            access_count: 1,
            last_accessed: now,
        }
    }

    fn access(&mut self) {
        self.access_count += 1;
        self.last_accessed = std::time::Instant::now();
    }

    fn is_expired(&self, ttl_seconds: u64) -> bool {
        self.created_at.elapsed().as_secs() > ttl_seconds
    }
}

impl CacheManager {
    /// Create a new cache manager with default configuration
    pub fn new() -> Self {
        Self::with_config(CacheConfig::default())
    }

    /// Create a new cache manager with custom configuration
    pub fn with_config(config: CacheConfig) -> Self {
        Self {
            config,
            l1_cache: Arc::new(DashMap::new()),
            l2_cache: Arc::new(DashMap::new()),
            stats: CacheStats::default(),
        }
    }

    /// Get a value from cache
    pub async fn get(&self, key: &str) -> Result<Option<Vec<u8>>> {
        // Try L1 cache first
        if let Some(mut entry) = self.l1_cache.get_mut(key) {
            if !self.is_entry_expired(&entry) {
                entry.access();
                return Ok(Some(entry.data.clone()));
            } else {
                // Remove expired entry
                drop(entry);
                self.l1_cache.remove(key);
            }
        }

        // Try L2 cache
        if let Some(mut entry) = self.l2_cache.get_mut(key) {
            if !self.is_entry_expired(&entry) {
                entry.access();
                let data = entry.data.clone();
                
                // Promote to L1 cache
                self.promote_to_l1(key, data.clone());
                
                return Ok(Some(data));
            } else {
                // Remove expired entry
                drop(entry);
                self.l2_cache.remove(key);
            }
        }

        Ok(None)
    }

    /// Put a value in cache
    pub async fn put(&self, key: &str, value: Vec<u8>) -> Result<()> {
        let entry = CacheEntry::new(value);

        // Always put in L1 first
        if self.l1_cache.len() >= self.config.l1_size {
            self.evict_l1().await;
        }

        self.l1_cache.insert(key.to_string(), entry);
        Ok(())
    }

    /// Remove a value from cache
    pub async fn remove(&self, key: &str) -> Result<bool> {
        let l1_removed = self.l1_cache.remove(key).is_some();
        let l2_removed = self.l2_cache.remove(key).is_some();
        Ok(l1_removed || l2_removed)
    }

    /// Clear all cached data
    pub async fn clear(&self) -> Result<()> {
        self.l1_cache.clear();
        self.l2_cache.clear();
        Ok(())
    }

    /// Get cache statistics
    pub fn stats(&self) -> &CacheStats {
        &self.stats
    }

    /// Check if cache contains a key
    pub async fn contains_key(&self, key: &str) -> bool {
        self.l1_cache.contains_key(key) || self.l2_cache.contains_key(key)
    }

    // Private helper methods

    fn is_entry_expired(&self, entry: &CacheEntry) -> bool {
        if let Some(ttl) = self.config.ttl_seconds {
            entry.is_expired(ttl)
        } else {
            false
        }
    }

    fn promote_to_l1(&self, key: &str, data: Vec<u8>) {
        if self.l1_cache.len() >= self.config.l1_size {
            // Would need to implement proper eviction
            return;
        }

        let entry = CacheEntry::new(data);
        self.l1_cache.insert(key.to_string(), entry);
        self.l2_cache.remove(key);
    }

    async fn evict_l1(&self) {
        // Simple eviction: move least recently used to L2
        if let Some((key, entry)) = self.find_lru_in_l1() {
            // Move to L2 if there's space
            if self.l2_cache.len() < self.config.l2_size {
                self.l2_cache.insert(key.clone(), entry);
            }
            self.l1_cache.remove(&key);
        }
    }

    fn find_lru_in_l1(&self) -> Option<(String, CacheEntry)> {
        let mut oldest_key = None;
        let mut oldest_time = std::time::Instant::now();

        for entry in self.l1_cache.iter() {
            let (key, value) = entry.pair();
            if value.last_accessed < oldest_time {
                oldest_time = value.last_accessed;
                oldest_key = Some(key.clone());
            }
        }

        if let Some(key) = oldest_key {
            if let Some((_, entry)) = self.l1_cache.remove(&key) {
                return Some((key, entry));
            }
        }

        None
    }
}

impl Default for CacheManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Cache statistics
#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub l1_size: usize,
    pub l2_size: usize,
}

impl CacheStats {
    pub fn hit_rate(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_cache_manager_creation() {
        let cache = CacheManager::new();
        assert_eq!(cache.config.l1_size, 1000);
        assert_eq!(cache.config.l2_size, 10000);
    }

    #[tokio::test]
    async fn test_cache_operations() {
        let cache = CacheManager::new();
        
        let key = "test_key";
        let value = b"test_value".to_vec();

        // Initially not present
        assert!(cache.get(key).await.unwrap().is_none());
        
        // Put and get
        cache.put(key, value.clone()).await.unwrap();
        let retrieved = cache.get(key).await.unwrap();
        assert_eq!(retrieved, Some(value));

        // Remove
        assert!(cache.remove(key).await.unwrap());
        assert!(cache.get(key).await.unwrap().is_none());
    }

    #[tokio::test]
    async fn test_cache_clear() {
        let cache = CacheManager::new();
        
        cache.put("key1", b"value1".to_vec()).await.unwrap();
        cache.put("key2", b"value2".to_vec()).await.unwrap();
        
        cache.clear().await.unwrap();
        
        assert!(cache.get("key1").await.unwrap().is_none());
        assert!(cache.get("key2").await.unwrap().is_none());
    }
}