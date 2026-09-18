import { BookOpen, Database, FlaskConical, Microscope } from "lucide-react";

export const EXPERTS = [
	{
		id: "training-advisor",
		icon: Database,
		titleKey: "aiChat.experts.trainingAdvisor.title",
		descriptionKey: "aiChat.experts.trainingAdvisor.description",
		sceneKey: "aiChat.experts.trainingAdvisor.scene",
		promptKey: "aiChat.scenarioCards.trainModel.prompt",
		tagKeys: [
			"aiChat.experts.trainingAdvisor.tag1",
			"aiChat.experts.trainingAdvisor.tag2",
		],
		helpKeys: [
			"aiChat.experts.trainingAdvisor.help1",
			"aiChat.experts.trainingAdvisor.help2",
			"aiChat.experts.trainingAdvisor.help3",
		],
		iconColor: "text-purple-600",
		sceneClass: "from-violet-100 to-purple-50",
	},
	{
		id: "validation-operator",
		icon: FlaskConical,
		titleKey: "aiChat.experts.validationOperator.title",
		descriptionKey: "aiChat.experts.validationOperator.description",
		sceneKey: "aiChat.experts.validationOperator.scene",
		promptKey: "aiChat.scenarioCards.testModel.prompt",
		tagKeys: [
			"aiChat.experts.validationOperator.tag1",
			"aiChat.experts.validationOperator.tag2",
		],
		helpKeys: [
			"aiChat.experts.validationOperator.help1",
			"aiChat.experts.validationOperator.help2",
			"aiChat.experts.validationOperator.help3",
		],
		iconColor: "text-emerald-600",
		sceneClass: "from-emerald-100 to-teal-50",
	},
	{
		id: "slide-analyst",
		icon: Microscope,
		titleKey: "aiChat.experts.slideAnalyst.title",
		descriptionKey: "aiChat.experts.slideAnalyst.description",
		sceneKey: "aiChat.experts.slideAnalyst.scene",
		promptKey: "aiChat.scenarioCards.browseImages.prompt",
		tagKeys: [
			"aiChat.experts.slideAnalyst.tag1",
			"aiChat.experts.slideAnalyst.tag2",
		],
		helpKeys: [
			"aiChat.experts.slideAnalyst.help1",
			"aiChat.experts.slideAnalyst.help2",
			"aiChat.experts.slideAnalyst.help3",
		],
		iconColor: "text-orange-600",
		sceneClass: "from-orange-100 to-amber-50",
	},
	{
		id: "literature-scout",
		icon: BookOpen,
		titleKey: "aiChat.experts.literatureScout.title",
		descriptionKey: "aiChat.experts.literatureScout.description",
		sceneKey: "aiChat.experts.literatureScout.scene",
		promptKey: "aiChat.experts.literatureScout.prompt",
		tagKeys: [
			"aiChat.experts.literatureScout.tag1",
			"aiChat.experts.literatureScout.tag2",
		],
		helpKeys: [
			"aiChat.experts.literatureScout.help1",
			"aiChat.experts.literatureScout.help2",
			"aiChat.experts.literatureScout.help3",
		],
		iconColor: "text-sky-600",
		sceneClass: "from-sky-100 to-blue-50",
	},
] as const;

export type Expert = (typeof EXPERTS)[number];
