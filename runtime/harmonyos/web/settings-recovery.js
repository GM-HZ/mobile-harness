// This code runs inside the bundled DSH General Settings module.
function MobileHarnessRecoveryRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	const css = DeveloperToolsRow_module_css_default;
	return react_jsx_runtime.jsxs("div", {
		className: css.row,
		children: [
			react_jsx_runtime.jsxs("div", {
				children: [
					react_jsx_runtime.jsx("div", {
						className: css.title,
						children: chinese ? "运行时恢复" : "Runtime recovery",
					}),
					react_jsx_runtime.jsx("div", {
						className: css.description,
						children: chinese ? "以安全模式或正常模式重新打开应用。" :
							"Reopen the app in safe or normal mode.",
					}),
				],
			}),
			react_jsx_runtime.jsx(_deepseek_ai_dsh_client_ui_primitives.Button, {
				variant: "outline",
				size: "sm",
				onClick: () => window.location.assign("/.mobile-harness/recovery"),
				children: chinese ? "恢复选项" : "Recovery options",
			}),
		],
	});
}

function registerMobileHarnessRecovery(ctx) {
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-recovery",
		order: 98,
		locale: NS,
	}, MobileHarnessRecoveryRow));
}
