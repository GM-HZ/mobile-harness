function MobileHarnessPrivacyRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "个人信息处理说明" : "Personal information",
		chinese ? "查看应用如何处理会话、文件和模型请求。" : "See how the app handles sessions, files, and model requests.",
		chinese ? "查看说明" : "View details", "/.mobile-harness/privacy");
}

function MobileHarnessNoticesRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "开源软件声明" : "Open source notices",
		chinese ? "查看随包组件和许可证。" : "See bundled components and their licenses.",
		chinese ? "查看声明" : "View notices", "/.mobile-harness/notices");
}

function registerMobileHarnessAppGallery(ctx) {
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-privacy",
		order: 99,
		locale: NS,
	}, MobileHarnessPrivacyRow));
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-notices",
		order: 100,
		locale: NS,
	}, MobileHarnessNoticesRow));
}
