# Contributing to cmd-vault

Thank you for your interest in contributing to `cmd-vault`!

## Guidelines

1. **Keep it Pure Stdlib**: `cmd-vault` has a strict zero-dependency policy. All code must use Python standard library modules.
2. **Write Unit Tests**: Ensure new functionality is thoroughly covered in `tests/test_vault.py`.
3. **Run Tests**: Verify test suite execution:
   ```bash
   python3 -m unittest discover -s tests
   ```
4. **Code Quality**: Follow PEP 8 style conventions. Keep code readable, robust, and well-documented.

## Development Workflow

1. Fork the repository on GitHub.
2. Clone your fork locally and create a topic branch (`git checkout -b feature/my-feature`).
3. Implement your changes and add unit tests.
4. Verify tests pass.
5. Push your branch and open a Pull Request against `modus-znz/cmd-vault`.
