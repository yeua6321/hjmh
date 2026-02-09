"""
Lunes 登录脚本
使用 Playwright 处理 Cloudflare Turnstile 验证码
支持本地和 CI 环境
添加了 Trace Viewer 调试功能
"""

import asyncio
from playwright.async_api import async_playwright, TimeoutError
import os
import json
import random
from datetime import datetime
from urllib.parse import quote
import traceback

# 检测是否在 CI 环境
IS_CI = os.getenv("CI", "false").lower() == "true"

# 从环境变量获取配置
EMAIL = os.getenv("LUNES_EMAIL", "")
PASSWORD = os.getenv("LUNES_PASSWORD", "")
LOGIN_NEXT_PATH = os.getenv("LUNES_NEXT_PATH", "/")


async def wait_for_turnstile_token(page, timeout=60000):
    """等待 Turnstile 验证码完成并返回有效 token"""
    print("等待 Turnstile 验证码加载...")
    
    # 在 CI 环境中，Turnstile 可能需要更长时间
    if IS_CI:
        print("   检测到 CI 环境，延长等待时间...")
        timeout = min(timeout * 2, 180000)  # 最多 3 分钟

    try:
        await page.wait_for_selector(
            'input[name="cf-turnstile-response"]',
            state="attached",
            timeout=timeout
        )
        
        # 添加随机延迟，使行为更像人类
        await asyncio.sleep(random.uniform(1, 3))

        for i in range(int(timeout / 1000)):
            if page.is_closed():
                print("⚠️ 页面已关闭，跳过 Turnstile 等待")
                return None

            current_url = page.url
            if "/login" not in current_url:
                print(f"✓ 已跳转到 {current_url}，无需继续等待 Turnstile")
                return None

            turnstile_token = await page.input_value('input[name="cf-turnstile-response"]')

            if turnstile_token and len(turnstile_token) > 0:
                print("✓ Turnstile 验证完成")
                return turnstile_token

            await asyncio.sleep(1)
            if i % 5 == 0 and i > 0:
                print(f"  等待中... ({i}秒)")

        raise TimeoutError("Turnstile token 未在规定时间内生成")

    except Exception as e:
        print(f"✗ Turnstile 验证失败: {e}")
        raise


async def login():
    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        trace_name = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        try:
            print("\n" + "="*60)
            print("🚀 启动浏览器...")
            print(f"   环境: {'CI (GitHub Actions)' if IS_CI else 'Local'}")
            print("="*60)

            # 根据环境选择浏览器配置
            if IS_CI:
                # CI 环境：使用 headless Chromium
                print("   使用 Chromium (headless)")
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-software-rasterizer',
                        '--disable-extensions',
                    ]
                )
            else:
                # 本地环境：使用可见的 Edge
                print("   使用 Edge (有界面)")
                browser = await p.chromium.launch(
                    channel="msedge",
                    headless=False,
                    args=['--disable-blink-features=AutomationControlled']
                )

            context = await browser.new_context(
                viewport={'width': 1024, 'height': 768},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='zh-CN',
            )

            # 启动 Trace 记录
            print("\n📹 启动 Trace 记录...")
            await context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True
            )
            print(f"✓ Trace 记录已启动")
            print(f"  保存文件名: {trace_name}")
            print("="*60 + "\n")

            page = await context.new_page()

            # 访问登录页面
            print("🌐 正在访问登录页面...")
            login_url = f"https://betadash.lunes.host/login?next={quote(LOGIN_NEXT_PATH, safe='/')}"
            print(f"   URL: {login_url}")
            print(f"   登录后跳转路径: {LOGIN_NEXT_PATH}")
            
            await page.goto(login_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 填写登录信息
            print("\n✏️  填写登录信息...")
            print(f"   邮箱: {EMAIL}")

            # 等待并填写邮箱
            email_input = page.locator('input[name="email"]')
            await email_input.wait_for(state="visible", timeout=10000)
            await email_input.click()
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await email_input.fill(EMAIL)

            await asyncio.sleep(random.uniform(0.3, 0.7))

            # 等待并填写密码
            password_input = page.locator('input[name="password"]')
            await password_input.wait_for(state="visible", timeout=10000)
            await password_input.click()
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await password_input.fill(PASSWORD)

            await asyncio.sleep(random.uniform(0.5, 1.0))

            # 验证填写结果
            email_value = await email_input.input_value()
            password_value = await password_input.input_value()

            print(f"   ✓ 邮箱已填写: {email_value}")
            print(f"   ✓ 密码已填写: {'*' * len(password_value)}")

            if not email_value or not password_value:
                print("\n⚠️  警告：表单未正确填写，尝试替代方法...")
                await page.locator('input[name="email"]').click()
                await page.keyboard.type(EMAIL, delay=100)
                await page.locator('input[name="password"]').click()
                await page.keyboard.type(PASSWORD, delay=100)
                await asyncio.sleep(1)

            # 等待 Turnstile 验证码
            print("\n🔐 处理 Cloudflare Turnstile 验证...")
            turnstile_token = await wait_for_turnstile_token(page, timeout=60000)
            if turnstile_token:
                print(f"   ✓ Token: {turnstile_token[:50]}...")

            # 提交表单
            print("\n📤 提交登录表单...")
            submit_button = page.locator('button[type="submit"]')
            await submit_button.click()

            # 等待导航
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except TimeoutError:
                print("   ⚠️  等待页面加载超时，继续检查...")

            await asyncio.sleep(2)

            # 检查登录结果
            current_url = page.url
            print(f"\n🔍 检查登录结果...")
            print(f"   当前 URL: {current_url}")

            if "/login" not in current_url:
                print("\n" + "="*60)
                print("✅ 登录成功!")
                print("="*60)

                # 获取 cookies
                cookies = await context.cookies()
                
                # 保存截图
                await page.screenshot(path="login_success.png")
                print("\n📸 截图已保存: login_success.png")

                # 尝试双击服务器卡片（如果需要）
                if not IS_CI:  # 仅在本地环境执行此操作
                    try:
                        server_card = page.locator('a.server-card:has-text("sumiesc")')
                        await server_card.wait_for(state="visible", timeout=10000)
                        print("\n🖱️  双击服务器卡片以进入详情...")
                        await server_card.dblclick()
                        await page.wait_for_load_state("domcontentloaded")
                        try:
                            await page.wait_for_url("**/servers/57811", timeout=10000)
                        except TimeoutError:
                            pass
                        await asyncio.sleep(1)
                        print(f"   ✓ 详情页 URL: {page.url}")
                        await page.screenshot(path="server_detail.png")
                        print("   📸 详情页截图已保存: server_detail.png")
                    except Exception as e:
                        print(f"   ⚠️  双击进入详情失败: {e}")

                # 保存 Trace (成功场景)
                success_trace = f"success_{trace_name}"
                await context.tracing.stop(path=success_trace)
                print(f"\n📹 Trace 已保存: {success_trace}")
                print(f"   查看方法: playwright show-trace {success_trace}")
                print("="*60 + "\n")

                if not IS_CI:
                    await asyncio.sleep(3)
                
                await browser.close()
                return cookies
            else:
                print("\n" + "="*60)
                print("❌ 登录失败!")
                print("="*60)

                await page.screenshot(path="login_failed.png")
                print("\n📸 截图已保存: login_failed.png")

                # 尝试获取错误消息
                try:
                    error_selectors = [
                        '.error',
                        '.alert-error',
                        '[role="alert"]',
                        '.text-red-500',
                        '.error-message'
                    ]
                    for selector in error_selectors:
                        error_element = page.locator(selector)
                        if await error_element.count() > 0:
                            error_msg = await error_element.first.text_content()
                            print(f"   错误消息: {error_msg}")
                            break
                except Exception as e:
                    print(f"   无法获取错误消息: {e}")

                # 保存 Trace (失败场景)
                failed_trace = f"failed_{trace_name}"
                await context.tracing.stop(path=failed_trace)
                print(f"\n📹 Trace 已保存: {failed_trace}")
                print(f"   查看方法: playwright show-trace {failed_trace}")
                print("="*60 + "\n")

                await browser.close()
                return None

        except Exception as e:
            print("\n" + "="*60)
            print(f"💥 发生错误: {e}")
            print("="*60)
            traceback.print_exc()

            try:
                if page and not page.is_closed():
                    await page.screenshot(path="error.png")
                    print("\n📸 错误截图已保存: error.png")

                if context:
                    error_trace = f"error_{trace_name}"
                    await context.tracing.stop(path=error_trace)
                    print(f"\n📹 Trace 已保存: {error_trace}")
                    print(f"   查看方法: playwright show-trace {error_trace}")
                    print("="*60 + "\n")

                if browser:
                    await browser.close()
            except Exception as cleanup_error:
                print(f"清理资源时出错: {cleanup_error}")

            return None


def main():
    """主函数"""
    # 验证必需的环境变量
    if not EMAIL or not PASSWORD:
        print("\n" + "="*60)
        print("❌ 错误：请设置 EMAIL 和 PASSWORD")
        print("="*60)
        print("\n配置方法:")
        print("  方法1: 直接在脚本中修改 EMAIL 和 PASSWORD 变量")
        print("  方法2: 设置环境变量 LUNES_EMAIL 和 LUNES_PASSWORD")
        print("\n示例 (Windows):")
        print('  set LUNES_EMAIL=your@email.com')
        print('  set LUNES_PASSWORD=yourpassword')
        print("\n示例 (Mac/Linux):")
        print('  export LUNES_EMAIL=your@email.com')
        print('  export LUNES_PASSWORD=yourpassword')
        print("\n示例 (GitHub Actions):")
        print('  在 Repository Settings → Secrets 中设置:')
        print('    LUNES_EMAIL')
        print('    LUNES_PASSWORD')
        print("="*60 + "\n")
        return 1

    print("\n" + "="*60)
    print("🚀 Lunes 自动登录脚本 (带 Trace 记录)")
    print("="*60)
    print(f"📧 邮箱: {EMAIL}")
    print(f"🔑 密码: {'*' * len(PASSWORD)}")
    print(f"🌍 环境: {'CI' if IS_CI else 'Local'}")
    print("="*60)

    # 运行登录
    cookies = asyncio.run(login())

    if cookies:
        print("\n" + "="*60)
        print("✅ 成功获取 Cookies")
        print("="*60)

        print(f"\n📋 Cookie 数量: {len(cookies)}")
        print("\nCookie 详情:")
        for i, cookie in enumerate(cookies, 1):
            value = cookie['value'][:50] if len(cookie['value']) > 50 else cookie['value']
            print(f"  {i}. {cookie['name']}: {value}...")

        # 保存 cookies
        with open('cookies.json', 'w', encoding='utf-8') as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)

        print("\n💾 Cookies 已保存到: cookies.json")
        print("="*60)

        print("\n🎉 登录流程完成!")
        print("\n📹 Trace 文件说明:")
        print("  - 使用 Trace Viewer 可以查看详细的操作记录")
        print("  - 包含: 截图、DOM 快照、网络请求、时间线等")
        print("  - 非常适合调试和分析问题")
        print("="*60 + "\n")
        return 0
    else:
        print("\n" + "="*60)
        print("❌ 登录失败")
        print("="*60)
        print("\n🔍 调试建议:")
        print("  1. 查看保存的截图文件 (login_failed.png 或 error.png)")
        print("  2. 使用 Trace Viewer 查看详细过程:")
        print("     playwright show-trace failed_trace_*.zip")
        print("  3. 检查邮箱和密码是否正确")
        print("  4. 确认网络连接正常")
        if IS_CI:
            print("  5. CI 环境可能被 Cloudflare 拦截，考虑使用代理")
        print("="*60 + "\n")
        return 1


if __name__ == "__main__":
    exit(main())
