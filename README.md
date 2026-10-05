  ```
- **Frontend TypeScript & Production Build**:
  ```bash
  cd frontend
  npm run build
  ```

### 6. Run Automated Unit Tests & Coverage
- **Backend Unit Tests & Coverage (>80%)**:
  ```bash
  cd backend
  uv run pytest --cov=api --cov-report=term-missing
  ```
- **Frontend Unit Tests & Coverage (>80%)**:
  ```bash
  cd frontend
  yarn test:coverage
  ```
