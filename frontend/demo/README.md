# 旧版 Demo 测试夹具

这里保留原前端 Demo 的虚构新闻、浏览器存储和模拟计时逻辑，仅由旧版 Demo 回归测试使用。

生产入口 `src/main.js`、页面、API 客户端均不得导入此目录。真实业务由 `src/composables/useAssistant.js` 调用后端完成；旧 localStorage 设置不会迁移或自动启用真实推送。
