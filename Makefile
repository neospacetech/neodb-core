# Makefile for NeoDB development

.PHONY: help install test lint format clean build docs bench

help:
	@echo "NeoDB Development Commands:"
	@echo "  install     Install Python dependencies"
	@echo "  test        Run all tests"
	@echo "  test-py     Run Python tests only"  
	@echo "  test-rust   Run Rust tests only"
	@echo "  lint        Lint all code"
	@echo "  format      Format all code"
	@echo "  clean       Clean build artifacts"
	@echo "  build       Build all components"
	@echo "  docs        Generate documentation"
	@echo "  bench       Run benchmarks"

# Installation
install:
	pip install -e ".[dev]"
	
install-rust:
	rustup update
	cargo --version

# Testing
test: test-py test-rust

test-py:
	pytest tests/ -v --cov=neodb --cov-report=term-missing

test-rust:
	cargo test --workspace

test-ci:
	pytest tests/ -v --cov=neodb --cov-report=xml

# Linting
lint: lint-py lint-rust

lint-py:
	flake8 src/ tests/
	mypy src/

lint-rust:
	cargo clippy --workspace -- -D warnings

# Formatting
format: format-py format-rust

format-py:
	black src/ tests/
	isort src/ tests/

format-rust:
	cargo fmt --all

# Cleaning
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	cargo clean

# Building
build: build-py build-rust

build-py:
	python -m build

build-rust:
	cargo build --workspace --release

# Documentation
docs:
	@echo "Building documentation..."
	# Add documentation generation commands here

# Benchmarks
bench:
	cargo bench --workspace

# Development setup
dev-setup: install install-rust
	@echo "Development environment setup complete!"

# Quick development checks
check: format lint test
	@echo "All checks passed!"

# Release preparation
release-prep: clean format lint test build
	@echo "Release preparation complete!"