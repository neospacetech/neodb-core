//! Concurrent cache implementation

use std::sync::Arc;
use dashmap::DashMap;
use parking_lot::RwLock;

/// Thread-safe concurrent cache
#[derive(Debug)]
pub struct ConcurrentCache<K: Clone + Eq + std::hash::Hash, V> {
    data: Arc<DashMap<K, V>>,
    stats: Arc<RwLock<CacheStats>>,
}

#[derive(Debug, Default, Clone, Copy)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub inserts: u64,
    pub removals: u64,
}

impl<K: Clone + Eq + std::hash::Hash, V: Clone> ConcurrentCache<K, V> {
    pub fn new() -> Self {
        Self {
            data: Arc::new(DashMap::new()),
            stats: Arc::new(RwLock::new(CacheStats::default())),
        }
    }

    pub fn get(&self, key: &K) -> Option<V> {
        let result = self.data.get(key).map(|entry| entry.value().clone());
        
        let mut stats = self.stats.write();
        if result.is_some() {
            stats.hits += 1;
        } else {
            stats.misses += 1;
        }
        
        result
    }

    pub fn insert(&self, key: K, value: V) -> Option<V> {
        let result = self.data.insert(key, value);
        self.stats.write().inserts += 1;
        result
    }

    pub fn remove(&self, key: &K) -> Option<(K, V)> {
        let result = self.data.remove(key);
        if result.is_some() {
            self.stats.write().removals += 1;
        }
        result
    }

    pub fn len(&self) -> usize {
        self.data.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    pub fn clear(&self) {
        let removed_count = self.data.len();
        self.data.clear();
        self.stats.write().removals += removed_count as u64;
    }

    pub fn stats(&self) -> CacheStats {
        *self.stats.read()
    }
}

impl<K: Clone + Eq + std::hash::Hash, V: Clone> Default for ConcurrentCache<K, V> {
    fn default() -> Self {
        Self::new()
    }
}

impl<K: Clone + Eq + std::hash::Hash, V> Clone for ConcurrentCache<K, V> {
    fn clone(&self) -> Self {
        Self {
            data: Arc::clone(&self.data),
            stats: Arc::clone(&self.stats),
        }
    }
}