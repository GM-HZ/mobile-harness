function MobileHarnessPrivacyRow() {
	const chinese = document.documentElement.lang.startsWith("zh");
	return MobileHarnessNavigationRow(chinese ? "个人信息处理说明" : "Personal information",
		chinese ? "查看应用如何处理会话、文件和模型请求。" : "See how the app handles sessions, files, and model requests.",
		chinese ? "查看说明" : "View details", "/.mobile-harness/privacy");
}

function registerMobileHarnessAppGallery(ctx) {
	ctx.slots.inject("settings.general.item", () => ctx.slots.register({
		name: "settings.general.item",
		id: "mobile-harness-privacy",
		order: 99,
		locale: NS,
	}, MobileHarnessPrivacyRow));
}
