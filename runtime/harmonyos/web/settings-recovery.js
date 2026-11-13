// This code runs inside the bundled DSH General Settings module.
function mobileHarnessSettingsRow(title, description, button, route) {
	const css = DeveloperToolsRow_module_css_default;
	return react_jsx_runtime.jsxs("div", {
		className: css.row,
		children: [
			react_jsx_runtime.jsxs("div", {
				children: [
					react_jsx_runtime.jsx("div", { className: css.title, children: title }),
					react_jsx_runtime.jsx("div", { className: css.description, children: description }),
				],
			}),
			react_jsx_runtime.jsx(_deepseek_ai_dsh_client_ui_primitives.Button, {
				variant: "outline",
				size: "sm",
				onClick: () => window.location.assign(route),
				children: button,
			}),
		],
	});
}

function MobileHarnessRecoveryRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return mobileHarnessSettingsRow(chinese ? "运行时恢复" : "Runtime recovery",
		chinese ? "以安全模式或正常模式重新打开应用。" : "Reopen the app in safe or normal mode.",
		chinese ? "恢复选项" : "Recovery options", "/.mobile-harness/recovery");
}

function MobileHarnessPrivacyRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return mobileHarnessSettingsRow(chinese ? "个人信息处理说明" : "Personal information",
		chinese ? "查看应用如何处理会话、文件和模型请求。" : "See how the app handles sessions, files, and model requests.",
		chinese ? "查看说明" : "View details", "/.mobile-harness/privacy");
}

function registerMobileHarnessSettings(ctx, appGallery) {
	ctx.slots.inject("settings.general.item", () => {
		ctx.slots.register({
			name: "settings.general.item",
			id: "mobile-harness-recovery",
			order: 98,
			locale: NS,
		}, MobileHarnessRecoveryRow);
		if (appGallery) {
			ctx.slots.register({
				name: "settings.general.item",
				id: "mobile-harness-privacy",
				order: 99,
				locale: NS,
			}, MobileHarnessPrivacyRow);
		}
	});
}
