"""
向量检索功能测试脚本
直接调用 CodeIndexerService，验证 ChromaDB 的表现
"""

import asyncio
import os
import sys

# 添加 backend 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.service.code_indexer import get_indexer


async def test_indexing_and_search():
    """测试索引构建和语义搜索"""

    # 1. 设置目标项目路径（指向 backend/app 目录）
    project_path = os.path.abspath("./app")
    print(f"🚀 开始为目录建立索引: {project_path}")

    # 2. 获取索引服务实例
    indexer = get_indexer(project_path)

    # 3. 执行索引（如果是第一次运行，会解析代码并建立向量索引）
    print("\n📚 正在解析代码库并建立索引...")
    chunks = indexer.extract_code_units(force_refresh=False)
    print(f"✅ 索引建立完成: {len(chunks)} 个代码块")

    # 显示项目结构摘要
    print("\n📊 项目结构摘要:")
    print(indexer.get_project_structure())

    # 4. 进行语义测试：使用意思相近但表述不同的查询词
    queries = [
        ("系统健康状态接口", "测试语义匹配：health_check -> 系统健康状态"),
        ("如何处理数据库连接", "测试语义匹配：database connection handling"),
        ("Pipeline 状态流转逻辑", "测试语义匹配：pipeline state management"),
        ("用户认证功能", "测试语义匹配：user authentication"),
        ("代码自动修复", "测试语义匹配：auto-fix / code repair"),
    ]

    print("\n" + "="*60)
    print("🔍 开始语义搜索测试")
    print("="*60)

    for query, description in queries:
        print(f"\n📝 查询: '{query}'")
        print(f"   说明: {description}")
        print("-" * 60)

        try:
            # 调用混合检索（关键词 + 向量）
            results = await indexer.semantic_search(
                query=query,
                top_k=2,
                use_vector=True,
                use_keyword=True
            )

            if results and "未找到" not in results:
                print(f"✅ 找到相关代码:")
                # 只打印前800字符
                print(results[:800])
                if len(results) > 800:
                    print(f"\n... (还有 {len(results) - 800} 字符)")
            else:
                print("❌ 未找到相关代码")

        except Exception as e:
            print(f"❌ 搜索出错: {e}")

    # 5. 测试两阶段检索
    print("\n" + "="*60)
    print("🔍 测试两阶段检索（签名 -> 实现）")
    print("="*60)

    query = "Pipeline"
    print(f"\n📝 第一阶段 - 搜索签名: '{query}'")

    try:
        signatures = await indexer.search_signatures(query, top_k=5)
        print("✅ 找到的签名列表:")
        print(signatures)

        # 如果找到结果，测试第二阶段
        if signatures and "未找到" not in signatures:
            print("\n📝 第二阶段 - 获取完整实现")
            # 解析第一个结果获取文件路径和名称
            lines = signatures.strip().split('\n')
            if lines:
                first_line = lines[0]
                # 简单解析：假设格式是 "1. [type] name - signature (file:line)"
                if '(' in first_line and ')' in first_line:
                    # 提取文件路径和名称
                    import re
                    match = re.search(r'\(([^:]+):(\d+)\)', first_line)
                    if match:
                        file_path = match.group(1)
                        # 提取名称（在 ] 和 ( 之间）
                        name_match = re.search(r'\]\s+(\w+)', first_line)
                        if name_match:
                            name = name_match.group(1)
                            print(f"   获取 {file_path} 中的 {name} 实现...")

                            implementation = await indexer.get_full_implementation(file_path, name)
                            if implementation:
                                print(f"✅ 完整实现 (前500字符):")
                                print(implementation[:500])
                            else:
                                print("❌ 未找到实现")

    except Exception as e:
        print(f"❌ 两阶段检索出错: {e}")

    print("\n" + "="*60)
    print("✅ 测试完成！")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_indexing_and_search())
