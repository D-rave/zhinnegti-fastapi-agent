.PHONY: help install dev test lint format build up down clean

# 默认显示帮助
help:
	@echo "智扫通智能客服 - 常用命令"
	@echo ""
	@echo "  make install     安装前后端依赖"
	@echo "  make dev         本地开发启动"
	@echo "  make test        运行测试"
	@echo "  make lint        代码检查"
	@echo "  make format      代码格式化"
	@echo "  make build       Docker 构建"
	@echo "  make up          Docker 启动"
	@echo "  make down        Docker 停止"
	@echo "  make clean       清理缓存和构建产物"

# ==================== 开发 ====================
install:
	cd backend && pip install -r requirements.txt && pip install -r requirements-dev.txt
	cd frontend && npm install

dev:
	@echo "请分别启动前后端："
	@echo "  后端: cd backend && python main.py"
	@echo "  前端: cd frontend && npm run dev"

# ==================== 测试 ====================
test:
	cd backend && pytest tests/ -v --cov=app --cov-report=html --cov-report=term

test-cov:
	cd backend && pytest tests/ -v --cov=app --cov-report=html
	@echo "覆盖率报告: backend/htmlcov/index.html"

# ==================== 代码规范 ====================
lint:
	cd backend && flake8 app/ tests/ && mypy app/
	cd frontend && npm run lint

format:
	cd backend && black app/ tests/ && isort app/ tests/
	cd frontend && npm run format

# ==================== Docker ====================
build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

# ==================== 清理 ====================
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.cache
	rm -rf backend/.mypy_cache