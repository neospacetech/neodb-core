//! LRU cache implementation

use std::collections::HashMap;
use std::hash::Hash;

/// Simple LRU cache implementation
#[derive(Debug)]
pub struct LruCache<K, V> {
    capacity: usize,
    map: HashMap<K, V>,
    // TODO: Add proper LRU ordering with linked list
}

impl<K: Clone + Hash + Eq, V> LruCache<K, V> {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            map: HashMap::with_capacity(capacity),
        }
    }

    pub fn get(&mut self, key: &K) -> Option<&V> {
        // TODO: Update LRU order
        self.map.get(key)
    }

    pub fn put(&mut self, key: K, value: V) -> Option<V> {
        if self.map.len() >= self.capacity && !self.map.contains_key(&key) {
            // TODO: Evict LRU item
        }
        self.map.insert(key, value)
    }

    pub fn remove(&mut self, key: &K) -> Option<V> {
        self.map.remove(key)
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }

    pub fn clear(&mut self) {
        self.map.clear();
    }
}