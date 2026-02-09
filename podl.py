"""
Lunes 登录脚本
使用 Playwright 处理 Cloudflare Turnstile 验证码
支持本地和 CI 环境
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
        # 先检查 Turnstile 输入框是否存在
        turnstile_count = await page.locator('input[name="cf-turnstile-response"]').count()
        
        if turnstile_count == 0:
            print("   ⚠️  未检测到 Turnstile 验证框，可能不需要验证")
            return None
        
        await page.wait_for_selector(
            'input[name="cf-turnstile-response"]',
            state="attached",
            timeout=10000  # 减少初始等待时间
        )
        
        # 添加随机延迟，使行为更像人类
        await asyncio.sleep(random.uniform(1, 3))

        # 设置最大等待时间
        max_wait = 30 if IS_CI else int(timeout / 1000)
        
        for i in range(max_wait):
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

        # 如果是 CI 环境，不抛出异常，返回 None 尝试继续
        if IS_CI:
            print(f"\n⚠️  Turnstile 验证超时 ({max_wait}秒)，CI 环境中尝试继续...")
            return None
        else:
            raise TimeoutError("Turnstile token 未在规定时间内生成")

    except TimeoutError as e:
        if IS_CI:
            print(f"⚠️  Turnstile 验证超时: {e}")
            print("   在 CI 环境中尝试继续执行...")
            return None
        else:
            print(f"✗ Turnstile 验证失败: {e}")
            raise
    except Exception as e:
        print(f"✗ Turnstile 处理异常: {e}")
        if IS_CI:
            print("   在 CI 环境中尝试继续执行...")
            return None
        else:
            raise


async def login():
    async with async_playwright() as p:
        browser = None
        context = None
        page = None

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

            page = await context.new_page()

            # 访问登录页面
            print("\n🌐 正在访问登录页面...")
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

            # 等待 Turnstile 验证码（但不强制要求完成）
            print("\n🔐 处理 Cloudflare Turnstile 验证...")
            try:
                turnstile_token = await wait_for_turnstile_token(page, timeout=60000)
                if turnstile_token:
                    print(f"   ✓ Token: {turnstile_token[:50]}...")
                else:
                    print(f"   ⚠️  未获取到 Turnstile token，尝试继续...")
            except Exception as e:
                print(f"   ⚠️  Turnstile 验证异常: {e}")
                if IS_CI:
                    print("   CI 环境中继续尝试提交...")
                else:
                    raise

            # 提交表单
            print("\n📤 提交登录表单...")
            submit_button = page.locator('button[type="submit"]')
            
            # 检查提交按钮是否可用
            try:
                is_disabled = await submit_button.get_attribute('disabled')
                if is_disabled:
                    print("   ⚠️  提交按钮被禁用，可能需要完成 Turnstile 验证")
                    if IS_CI:
                        print("   ⚠️  CI 环境可能无法绕过 Cloudflare 验证")
                        await page.screenshot(path="turnstile_blocked.png")
                        print("   📸 已保存截图: turnstile_blocked.png")
                        # 尝试等待按钮启用
                        print("   尝试等待提交按钮启用...")
                        for i in range(10):
                            await asyncio.sleep(1)
                            is_disabled = await submit_button.get_attribute('disabled')
                            if not is_disabled:
                                print(f"   ✓ 按钮已启用 (等待 {i+1} 秒)")
                                break
                        else:
                            print("   ✗ 按钮仍然被禁用，登录失败")
                            await browser.close()
                            return None
            except Exception as e:
                print(f"   检查按钮状态时出错: {e}，继续尝试提交...")
            
            # 尝试点击提交按钮
            try:
                await submit_button.click()
            except Exception as e:
                print(f"   ⚠️  点击提交按钮失败: {e}")
                print("   尝试使用 JavaScript 点击...")
                await submit_button.evaluate('el => el.click()')

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
                        '.error-message',
                        '.alert',
                        '.message'
                    ]
                    for selector in error_selectors:
                        error_element = page.locator(selector)
                        if await error_element.count() > 0:
                            error_msg = await error_element.first.text_content()
                            if error_msg and error_msg.strip():
                                print(f"   错误消息: {error_msg.strip()}")
                                break
                except Exception as e:
                    print(f"   无法获取错误消息: {e}")

                # 获取页面内容用于调试
                if IS_CI:
                    try:
                        page_content = await page.content()
                        with open('page_content.html', 'w', encoding='utf-8') as f:
                            f.write(page_content)
                        print("   📄 页面内容已保存: page_content.html")
                    except Exception as e:
                        print(f"   无法保存页面内容: {e}")

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
                    
                    # 在 CI 环境保存页面内容
                    if IS_CI:
                        try:
                            page_content = await page.content()
                            with open('error_page.html', 'w', encoding='utf-8') as f:
                                f.write(page_content)
                            print("   📄 错误页面内容已保存: error_page.html")
                        except:
                            pass

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
        print("  方法2: 设置环境变量 LUNES_EMAIL 和 
