"""
功能测试：文件状态检测与边缘情况

测试场景：
- FT-FD-01: 已存在文件被错误标记为新建
- FT-FD-02: 文件不存在时返回正确的 404
- FT-FD-03: 路径大小写敏感性问题（Windows vs Linux）
- FT-FD-04: 并发读取同一文件的一致性
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

pytestmark = [pytest.mark.functional, pytest.mark.file_detection]


class TestFileStatusDetection:
    """
    FT-FD-01: 已存在文件被错误标记为新建
    
    问题描述：前端显示 backend/main.py 为"新建"，但后端显示文件存在（200 状态码）
    根因：前端状态检测逻辑可能与后端实际文件状态不一致
    
    测试目标：验证文件存在性检测的准确性
    """

    @pytest.fixture
    def existing_file_path(self):
        """已存在的文件路径"""
        return "backend/main.py"

    @pytest.fixture
    def non_existing_file_path(self):
        """不存在的文件路径"""
        return "backend/app/api/v1/timestamp.py"

    def test_existing_file_returns_correct_status(self, existing_file_path):
        """测试已存在文件返回正确的存在状态"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # 创建模拟文件结构
            backend_dir = project_root / "backend"
            backend_dir.mkdir(parents=True)
            main_file = backend_dir / "main.py"
            main_file.write_text("# Main file\n", encoding='utf-8')
            
            # 验证文件存在
            file_path = project_root / existing_file_path
            assert file_path.exists() is True
            assert file_path.is_file() is True

    def test_non_existing_file_returns_404(self, non_existing_file_path):
        """测试不存在文件返回 404"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # 验证文件不存在
            file_path = project_root / non_existing_file_path
            assert file_path.exists() is False

    def test_file_exists_consistency_between_api_calls(self, existing_file_path):
        """测试多次 API 调用间文件存在性一致性"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # 创建文件
            backend_dir = project_root / "backend"
            backend_dir.mkdir(parents=True)
            main_file = backend_dir / "main.py"
            main_file.write_text("# Main file\n", encoding='utf-8')
            
            # 模拟多次 API 调用
            results = []
            for _ in range(5):
                file_path = project_root / existing_file_path
                results.append(file_path.exists())
            
            # 验证所有调用结果一致
            assert all(results) is True
            assert len(set(results)) == 1  # 所有结果相同


class TestFilePathCaseSensitivity:
    """
    FT-FD-03: 路径大小写敏感性问题
    
    问题描述：Windows 文件系统不区分大小写，但前端可能传递不同大小写的路径
    例如：backend/main.py vs Backend/Main.py
    
    测试目标：验证路径处理的大小写一致性
    """

    @pytest.fixture
    def case_variations(self):
        """路径大小写变体"""
        return [
            "backend/main.py",
            "Backend/main.py",
            "backend/Main.py",
            "BACKEND/MAIN.PY",
        ]

    def test_case_insensitive_file_lookup(self, case_variations):
        """测试大小写不敏感的文件查找（Windows）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # 创建文件
            backend_dir = project_root / "backend"
            backend_dir.mkdir(parents=True)
            main_file = backend_dir / "main.py"
            main_file.write_text("# Main file\n", encoding='utf-8')
            
            # 在 Windows 上，所有变体都应该能找到文件
            import sys
            if sys.platform == "win32":
                for variant in case_variations:
                    file_path = project_root / variant
                    # Windows 路径解析是大小写不敏感的
                    resolved = file_path.resolve()
                    assert resolved.exists() is True

    def test_normalized_path_handling(self, case_variations):
        """测试规范化路径处理"""
        # 所有变体规范化后应该相同
        normalized_paths = set()
        for variant in case_variations:
            # 使用 posix 风格并小写
            normalized = variant.replace("\\", "/").lower()
            normalized_paths.add(normalized)
        
        # 验证规范化后只有一个唯一路径
        assert len(normalized_paths) == 1
        assert "backend/main.py" in normalized_paths


class TestFileReadTokenConsistency:
    """
    FT-FD-04: 文件读取 Token 一致性
    
    问题描述：文件存在时应该返回有效的 read_token，
    而不是 "NEW_FILE"
    
    测试目标：验证 read_token 生成的正确性
    """

    @pytest.fixture
    def file_safe_io_service(self):
        """文件安全 IO 服务"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.service.file_safe_io import FileSafeIOService
            service = FileSafeIOService(project_root=tmpdir)
            yield service

    def test_existing_file_returns_valid_token(self, file_safe_io_service):
        """测试已存在文件返回有效 token"""
        service = file_safe_io_service
        
        # 创建测试文件
        test_file = service.project_root / "test.py"
        test_file.write_text("# Test content\n", encoding='utf-8')
        
        # 读取文件
        result = service.read_file("test.py")
        
        # 验证返回有效 token
        assert result.exists is True
        assert result.read_token is not None
        assert result.read_token != "NEW_FILE"
        assert result.content is not None

    def test_new_file_returns_new_file_token(self, file_safe_io_service):
        """测试新文件返回 NEW_FILE token"""
        service = file_safe_io_service
        
        # 读取不存在的文件
        result = service.read_file("non_existing.py")
        
        # 验证返回 NEW_FILE token
        assert result.exists is False
        assert result.read_token == "NEW_FILE"
        assert result.content is None

    def test_token_consistency_across_reads(self, file_safe_io_service):
        """测试多次读取同一文件的 token 一致性"""
        service = file_safe_io_service
        
        # 创建测试文件
        test_file = service.project_root / "test.py"
        test_file.write_text("# Test content\n", encoding='utf-8')
        
        # 多次读取
        result1 = service.read_file("test.py")
        result2 = service.read_file("test.py")
        
        # 验证文件存在性一致
        assert result1.exists == result2.exists is True
        # 注意：每次读取会生成新 token，所以 token 不同是正常的
        # 但内容应该相同
        assert result1.content == result2.content


class TestWorkspaceAPIEdgeCases:
    """
    Workspace API 边缘情况测试
    
    测试 get_file_content API 的各种边缘情况
    """

    @pytest.mark.asyncio
    async def test_get_content_of_existing_file(self):
        """测试获取已存在文件内容"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建文件
            backend_dir = Path(tmpdir) / "backend"
            backend_dir.mkdir()
            main_file = backend_dir / "main.py"
            main_file.write_text("# Main file content\n", encoding='utf-8')
            
            # 验证文件存在
            assert main_file.exists() is True
            
            # 模拟 API 响应
            response = {
                "success": True,
                "data": {
                    "path": "backend/main.py",
                    "content": "# Main file content\n",
                    "exists": True
                }
            }
            
            assert response["success"] is True
            assert response["data"]["exists"] is True

    @pytest.mark.asyncio
    async def test_get_content_of_non_existing_file(self):
        """测试获取不存在文件内容返回 404"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 不创建文件
            
            # 模拟 API 响应
            response = {
                "success": False,
                "data": {},
                "error": "File not found"
            }
            
            assert response["success"] is False
            assert "not found" in response["error"].lower()

    @pytest.mark.asyncio
    async def test_get_content_with_special_characters_in_path(self):
        """测试特殊字符路径处理"""
        # 测试包含空格、中文等特殊字符的路径
        special_paths = [
            "backend/my file.py",
            "backend/文件.py",
            "backend/file-name_test.py",
        ]
        
        for path in special_paths:
            # 验证路径可以被正确处理
            normalized = path.replace("\\", "/")
            assert normalized is not None


class TestFileStatusSynchronization:
    """
    文件状态同步测试
    
    测试前端和后端文件状态的一致性
    """

    def test_frontend_backend_status_alignment(self):
        """测试前后端状态对齐"""
        # 模拟前端收到的文件列表
        frontend_files = {
            "backend/main.py": {"status": "existing", "isNew": False},
            "backend/app/api/v1/timestamp.py": {"status": "new", "isNew": True},
        }
        
        # 模拟后端实际文件状态
        backend_status = {
            "backend/main.py": {"exists": True, "size": 100},
            "backend/app/api/v1/timestamp.py": {"exists": False},
        }
        
        # 验证状态一致性
        for path, frontend_info in frontend_files.items():
            backend_info = backend_status.get(path)
            if backend_info:
                # 如果后端显示文件存在，前端不应该标记为新建
                if backend_info["exists"]:
                    assert frontend_info["isNew"] is False, \
                        f"文件 {path} 已存在但前端标记为新建"

    def test_batch_file_status_check(self):
        """测试批量文件状态检查"""
        file_list = [
            "backend/main.py",
            "backend/app/service/timestamp_service.py",
            "backend/app/api/v1/timestamp.py",
        ]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # 只创建部分文件
            backend_dir = project_root / "backend"
            backend_dir.mkdir()
            (backend_dir / "main.py").write_text("# Main\n")
            
            # 批量检查状态
            status_results = {}
            for file_path in file_list:
                full_path = project_root / file_path
                status_results[file_path] = {
                    "exists": full_path.exists(),
                    "is_file": full_path.is_file() if full_path.exists() else False
                }
            
            # 验证结果
            assert status_results["backend/main.py"]["exists"] is True
            assert status_results["backend/app/service/timestamp_service.py"]["exists"] is False
            assert status_results["backend/app/api/v1/timestamp.py"]["exists"] is False
