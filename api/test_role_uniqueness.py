"""
临时测试：验证角色编码唯一性校验
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_role_code_uniqueness():
    """测试角色编码唯一性校验"""
    print("\n=== 测试角色编码唯一性校验 ===")

    # 注意：这是一个手动测试，需要有效的认证token
    # 实际运行时需要替换为真实的token
    print("此测试需要手动运行，需要：")
    print("1. 有效的认证token")
    print("2. role.manage权限")
    print("3. 数据库连接")
    print("\n预期行为：")
    print("- 创建新角色成功")
    print("- 使用相同编码再次创建时，返回 400 错误")
    print("- 错误消息为：'角色编码已存在，请使用其他编码'")

if __name__ == "__main__":
    test_role_code_uniqueness()
