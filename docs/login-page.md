# 博维登录页

登录页复用现有后端账号密码会话和企业微信 OAuth，不新建账号体系、不开放自助注册。
未认证时 LoginGate 不挂载工作台与业务页面；账号登录保留当前地址，企业微信登录通过短时同源路径恢复原地址。服务故障与未登录状态分开处理。

## 验证

```sh
npx vitest run src/pages/LoginPage.test.tsx src/layouts/AppLayout.test.tsx src/components/IdentityMenu.test.tsx src/auth/RouteGuard.test.tsx
node scripts/login.ui-qa.mjs
npm run build
```

浏览器验收使用模拟认证失败响应，不使用真实凭据。实际企业微信扫码、企业微信客户端授权以及生产账号登录需要在配置完成的部署环境验证。

## 视觉素材

沿用已确认的咨询报告 / 玻璃层次效果稿，标题、品牌 Logo、登录面板全部为真实 HTML/CSS 组件；手机改为单列。

背景路径：`public/login-consulting-scene.png`。使用内置 imagegen 编辑生成，未使用 CLI。参考图为用户确认的第三版登录效果稿。最终生成提示词：

> Edit this approved login mockup into a production website BACKGROUND ONLY. Keep exactly the bright pale blue-white architectural office environment, distant skyline, lighting, and three glass-edged consulting report panels in the lower left. Remove the top-left logo, gold short line, large Chinese heading and subtitle completely, leaving clean pale space for live HTML text there. Remove the ENTIRE right login panel including its frame and all UI text and buttons, leaving unobstructed continuous softly blurred pale architecture on the right for an HTML form. Preserve left reports and perspective without increasing their size. Wide landscape 16:9. No new text, no new logos, no new objects. This is an architectural background asset, not a UI screenshot.
