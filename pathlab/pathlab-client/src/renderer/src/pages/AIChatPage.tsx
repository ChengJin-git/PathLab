import {
	Bot,
	ChevronDown,
	ChevronLeft,
	ChevronRight,
	Clock,
	ClipboardList,
	Database,
	FileSpreadsheet,
	Share2,
	History,
	Loader2,
	Menu,
	MessageSquare,
	Mic,
	MicOff,
	Paperclip,
	Plus,
	Send,
	Sparkles,
	Square,
	ThumbsDown,
	ThumbsUp,
	Trash2,
	User,
	Wrench,
	X,
} from "lucide-react";
import type React from "react";
import {
		Fragment,
	useCallback,
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { useTranslation } from "react-i18next";
import { getSidebarToggleBarClassName } from "../lib/aiChatSidebarLayout";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
	activateMessageVariant,
	addMessage,
	type ChatMessage,
	type ChatMessageContent,
	type Conversation,
	type ConversationWithMessages,
	cancelChatPatchInferenceOnExit,
	chatWithAI,
	createConversation,
	deleteConversation,
	deleteMessagesFrom,
	downloadBlobFile,
	generateConversationTitle,
	getConversation,
	getConversationFeedbacks,
	getConversations,
	type MessageArtifacts,
	type PdfParseResultEvent,
	submitMessageFeedback,
	updateMessage,
	type WebSearchResultEvent,
} from "../api";
// Extracted modules
import AssistantMessage, {
	isInternalOnlyMessage,
	parseCancelTaskNow,
	parseSubmitTask,
	removeContextLimitBlock,
	removeResponseTruncatedBlock,
} from "../components/chat/AssistantMessage";
import { parseCancelTaskConfig } from "../components/chat/CancelTaskCard";
import { removeChartConfigBlock } from "../components/chat/ChartCard";
import { removeCSVActionBlock } from "../components/chat/CSVActionCard";
import {
	CSVPreviewCard,
	parseCSVPreview,
	removeCSVPreviewBlock,
} from "../components/chat/CSVPreviewCard";
import { removeImageRecommendationBlock } from "../components/chat/ImageRecommendationCard";
import { removeMetricConfigBlock } from "../components/chat/MetricCard";
import { removeModelListBlock } from "../components/chat/ModelListCard";
import { removeNavigateBlock } from "../components/chat/NavigationCard";
// Chat component imports still needed by AIChatPage main body
import { removeOptionsBlock } from "../components/chat/OptionButtons";
import {
	parsePatchInferenceConfig,
	removePatchInferenceBlock,
} from "../components/chat/PatchInferenceCard";
import {
	type CachedAnalysisData,
	removeQuickAnalysisConfigBlock,
} from "../components/chat/QuickAnalysisViewer";
import {
	parseTaskConfig,
	removeTaskConfigBlock,
} from "../components/chat/TaskConfigCard";
import type { CachedTaskData } from "../components/chat/TaskHistoryCard";
import { Tooltip } from "../components/ui/tooltip";
import { removeVoiceControlBlock } from "../components/chat/VoiceControlBlock";
import { AudioVisualizer } from "../components/common/AudioVisualizer";
import { MULTIMODAL_MODELS } from "../components/settings/GeneralTab";
import { SCENARIO_CARDS } from "../constants/scenarios";
import { BEFORE_LOGOUT_EVENT, useAuth } from "../contexts/AuthContext";
import {
	isPdfContextMessage,
		removeInternalMetadataBlocks,
	preserveContentOnClearMarker,
	sanitizeConfigBlocksForAI,
} from "../lib/chatMessageParser";
import { mergeLoadedMessagesWithPendingAssistant } from "../lib/chatPendingMessageState";
import { xlsxToCSV } from "../lib/csvImporter";
import { useVoiceSession } from "../lib/useVoiceSession";
import { formatFileSize } from "../lib/utils";

interface RegenerationVariant {
	id: string;
	content: string;
	timestamp: Date;
	artifacts?: MessageArtifacts;
}

interface Message {
	id: string;
	role: "user" | "assistant";
	content: string;
	images?: string[]; // base64 images for display
	timestamp: Date;
	csvAttachments?: { fileName: string; content: string }[]; // CSV file contents for processing
	artifacts?: MessageArtifacts;
	regenerations?: RegenerationVariant[];
	activeRegenerationIndex?: number;
}

interface ImageAttachment {
	id: string;
	file: File;
	preview: string; // base64 data URL for preview
	base64: string; // base64 data for API
}

interface FileAttachment {
	id: string;
	file: File;
	name: string;
	type: "csv" | "xlsx";
	content: string; // text content for CSV, parsed content for XLSX
	preview: string[]; // first few rows for preview
}

const BACKEND_MESSAGE_ID_THRESHOLD = 1000000000;

const getPersistedMessageId = (messageId: string): number | null => {
	const numericId = parseInt(messageId, 10);
	if (Number.isNaN(numericId) || numericId >= BACKEND_MESSAGE_ID_THRESHOLD) {
		return null;
	}
	return numericId;
};

const hasReplayableAttachmentData = (message: Message): boolean =>
	!parseCSVPreview(message.content) || Boolean(message.csvAttachments?.length);

const BranchForkIcon = ({
	className,
	...props
}: React.SVGProps<SVGSVGElement>) => (
	<svg
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		strokeWidth="1.9"
		strokeLinecap="round"
		strokeLinejoin="round"
		className={className}
		aria-hidden="true"
		{...props}
	>
		<circle cx="7" cy="5" r="2.25" />
		<circle cx="17" cy="5" r="2.25" />
		<circle cx="12" cy="19" r="2.25" />
		<path d="M7 7.25v2.5a4 4 0 0 0 4 4h1" />
		<path d="M17 7.25v2.5a4 4 0 0 1-4 4h-1" />
		<path d="M12 14v2.75" />
	</svg>
);

const isMessageHiddenInTimeline = (message: Message): boolean =>
	(message.role === "assistant" && isInternalOnlyMessage(message.content)) ||
	(message.role === "user" && isPdfContextMessage(message.content));

const PENDING_CANCELLED_RESPONSE_KEY_PREFIX =
	"ai-chat-pending-cancelled-response:";
const PENDING_CANCELLED_RESPONSE_RETRY_DELAY_MS = 1200;
const PENDING_CANCELLED_RESPONSE_MAX_RETRIES = 5;
const PENDING_PATCH_INFERENCE_CANCEL_KEY_PREFIX =
	"ai-chat-pending-patch-inference-cancel:";
const PENDING_PATCH_INFERENCE_CANCEL_RETRY_DELAY_MS = 1200;
const PENDING_PATCH_INFERENCE_CANCEL_MAX_RETRIES = 5;
const conversationHistoryCache = new Map<string, Conversation[]>();

const getPendingCancelledResponseKey = (conversationId: string) =>
	`${PENDING_CANCELLED_RESPONSE_KEY_PREFIX}${conversationId}`;

const getPendingPatchInferenceCancelKey = (conversationId: string) =>
	`${PENDING_PATCH_INFERENCE_CANCEL_KEY_PREFIX}${conversationId}`;

interface PendingPatchInferenceCancel {
	messageId: number;
	content: string;
	timestamp: number;
}

function hasActivePatchInferenceRun(
	content: string | null | undefined,
): boolean {
	if (!content) return false;

	const config = parsePatchInferenceConfig(content);
	if (!config) return false;

	return [config.classification_run, config.segmentation_run].some(
		(run) =>
			Boolean(run?.task_id) &&
			(run?.status === "queued" || run?.status === "running"),
	);
}

function hasPersistedPatchInferenceCancellation(
	messages: ConversationWithMessages["messages"],
	pending: PendingPatchInferenceCancel,
): boolean {
	const targetMessage = messages.find(
		(message) => message.id === pending.messageId,
	);
	if (!targetMessage || targetMessage.role !== "assistant") return false;

	return !hasActivePatchInferenceRun(targetMessage.content);
}

function readPendingPatchInferenceCancel(
	conversationId: string,
): PendingPatchInferenceCancel | null {
	const raw = sessionStorage.getItem(
		getPendingPatchInferenceCancelKey(conversationId),
	);
	if (!raw) return null;

	try {
		const parsed = JSON.parse(raw) as Partial<PendingPatchInferenceCancel>;
		if (
			typeof parsed.messageId === "number" &&
			typeof parsed.content === "string" &&
			typeof parsed.timestamp === "number"
		) {
			return {
				messageId: parsed.messageId,
				content: parsed.content,
				timestamp: parsed.timestamp,
			};
		}
	} catch {
		// Ignore malformed pending payloads.
	}

	sessionStorage.removeItem(getPendingPatchInferenceCancelKey(conversationId));
	return null;
}

const getConversationUpdatedAt = (conversation: Conversation): number => {
	const timestamp = new Date(conversation.updated_at).getTime();
	return Number.isNaN(timestamp) ? 0 : timestamp;
};

const sortConversationsByUpdatedAt = (items: Conversation[]): Conversation[] =>
	[...items].sort(
		(a, b) => getConversationUpdatedAt(b) - getConversationUpdatedAt(a),
	);

const upsertConversation = (
	items: Conversation[],
	conversation: Conversation,
): Conversation[] =>
	sortConversationsByUpdatedAt([
		conversation,
		...items.filter(
			(item) => item.conversation_id !== conversation.conversation_id,
		),
	]);

export default function AIChatPage() {
	const navigate = useNavigate();
	const location = useLocation();
	const { conversationId: urlConversationId } = useParams<{
		conversationId?: string;
	}>();
	const { t } = useTranslation();
	const { user, isLoading: isAuthLoading } = useAuth();

	// Chat state
	const [messages, setMessages] = useState<Message[]>([]);
	const draftInputKey = `draft:chat:input:${urlConversationId ?? 'new'}`
	const [input, setInput] = useState(() => {
		try {
			const stored = sessionStorage.getItem(draftInputKey)
			if (stored !== null) return stored
		} catch {}
		return ""
	});

	// Generation lifecycle: single enum replaces 3 independent booleans
	// idle → thinking (waiting for first chunk) → streaming (receiving chunks) → idle
	type GenerationPhase = "idle" | "thinking" | "streaming";
	const [generationPhase, setGenerationPhase] =
		useState<GenerationPhase>("idle");
	const isLoading = generationPhase === "thinking";
	const isGenerating = generationPhase !== "idle";
	const generationPhaseRef = useRef<GenerationPhase>("idle");
	generationPhaseRef.current = generationPhase;

	const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>(
		[],
	);
	const [fileAttachments, setFileAttachments] = useState<FileAttachment[]>([]);
	const [isDraggingFile, setIsDraggingFile] = useState(false);
	// Monotonic counter to distinguish active generation from stale ones
	const generationIdRef = useRef(0);

	// Conversation management
	const [conversations, setConversations] = useState<Conversation[]>([]);
	const [currentConversationMeta, setCurrentConversationMeta] = useState<
		Conversation | ConversationWithMessages | null
	>(null);
	const [currentConversationId, setCurrentConversationId] = useState<
		string | null
	>(null);
	const currentConversationIdRef = useRef<string | null>(null);
	currentConversationIdRef.current = currentConversationId;
	const untitledBranchConversationIdsRef = useRef<Set<string>>(new Set());
	const [pendingTitleConvIds, setPendingTitleConvIds] = useState<Set<string>>(new Set());
	// Initialize from localStorage, defaulting to true on desktop, false on mobile
	const [showHistory, setShowHistory] = useState(() => {
		// Mobile always defaults to hidden (false) regardless of previous state
		if (window.innerWidth < 1024) {
			return false;
		}

		const saved = localStorage.getItem("ai-chat-sidebar-open");
		if (saved !== null) {
			return saved === "true";
		}
		return true;
	});

	// Persist sidebar state
	useEffect(() => {
		localStorage.setItem("ai-chat-sidebar-open", String(showHistory));
	}, [showHistory]);

	// Listen for mobile sidebar toggle from Layout header hamburger button
	useEffect(() => {
		const handleToggle = () => setShowHistory((prev) => !prev);
		window.addEventListener("toggle-ai-sidebar", handleToggle);
		return () => window.removeEventListener("toggle-ai-sidebar", handleToggle);
	}, []);

	const [isLoadingConversations, setIsLoadingConversations] = useState(false);
	const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

	// UI state
	const [showWelcomeHero, setShowWelcomeHero] = useState(true);
	const [toastMessage, setToastMessage] = useState<{
		type: "error" | "success" | "info";
		message: string;
	} | null>(null);

	// Feedback state: messageId -> feedback type
	const [feedbacks, setFeedbacks] = useState<
		Map<number, "thumbs_up" | "thumbs_down">
	>(new Map());
	const [pendingFeedbackIds, setPendingFeedbackIds] = useState<Set<number>>(
		new Set(),
	);
	// Helpfulness feedback state: messageId -> helpfulness type (for task submission feedback)
	const [helpfulnessFeedbacks, setHelpfulnessFeedbacks] = useState<
		Map<number, "helpful" | "not_helpful">
	>(new Map());

	// Voice command submit trigger: when this changes, trigger submit on TaskConfigCard
	const [submitTaskTrigger, setSubmitTaskTrigger] = useState<number>(0);
	// Voice command cancel trigger: when this changes, trigger cancel on CancelTaskCard
	const [cancelTaskTrigger, setCancelTaskTrigger] = useState<number>(0);

	// Refs
	const messagesEndRef = useRef<HTMLDivElement>(null);
	const messagesContainerRef = useRef<HTMLDivElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const initialMessageSent = useRef(false);
	const scrollRestoredRef = useRef(false);
	// Ref for aborting AI generation
	const abortControllerRef = useRef<AbortController | null>(null);
	// Ref to access latest messages in callbacks
	const messagesRef = useRef<Message[]>([]);
	messagesRef.current = messages;
	const pendingCancelledRetryTimersRef = useRef<Map<string, number>>(new Map());
	const pendingPatchInferenceCancelRetryTimersRef = useRef<Map<string, number>>(
		new Map(),
	);
	// Ref to skip loading conversation when we just created it (to avoid overwriting in-progress messages)
	const skipConversationLoadRef = useRef(false);
	// Ref to track current input value for voice transcript appending
	const inputRef = useRef("");
	inputRef.current = input;
	const pendingProgrammaticSubmitRef = useRef(false);

	useEffect(() => {
		try { sessionStorage.setItem(draftInputKey, input) } catch {}
	}, [draftInputKey, input])

	const formRef = useRef<HTMLFormElement>(null);

	// ── Smart auto-scroll ──────────────────────────────────────────────────
	// Track whether the user has intentionally scrolled away from the bottom.
	// When true we suppress auto-scroll so the user can read earlier content
	// while new chunks keep streaming in.
	const userScrolledAwayRef = useRef(false);
	const [hasScrolledAway, setHasScrolledAway] = useState(false);
	const scrollRafRef = useRef<number | null>(null);

	// Helper: is the scroll container "near bottom"? (within 150px)
	const isNearBottom = useCallback(() => {
		const el = messagesContainerRef.current;
		if (!el) return true;
		return el.scrollHeight - el.scrollTop - el.clientHeight < 150;
	}, []);

	const scrollToBottom = useCallback(() => {
		// Skip if user has scrolled away — let them read in peace
		if (userScrolledAwayRef.current) return;
		if (scrollRafRef.current !== null) return; // already scheduled
		scrollRafRef.current = requestAnimationFrame(() => {
			scrollRafRef.current = null;
			messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
		});
	}, []);

	// Detect user scroll intent via wheel / touchmove on the messages container.
	// When user scrolls UP → mark as "scrolled away".
	// When user scrolls back to near-bottom → reset so auto-scroll resumes.
	useEffect(() => {
		const el = messagesContainerRef.current;
		if (!el) return;

		const handleUserScroll = () => {
			if (isNearBottom()) {
				userScrolledAwayRef.current = false;
				setHasScrolledAway(false);
			} else {
				userScrolledAwayRef.current = true;
				setHasScrolledAway(true);
			}
		};

		el.addEventListener("scroll", handleUserScroll, { passive: true });
		return () => el.removeEventListener("scroll", handleUserScroll);
	}, [isNearBottom]);

	// Programmatically submit the chat form after setting input.
	// Uses ref-based approach instead of DOM query to avoid fragile setTimeout + querySelector patterns.
	const submitFormProgrammatically = useCallback((text: string) => {
		if (
			generationPhaseRef.current !== "idle" ||
			pendingProgrammaticSubmitRef.current
		) {
			return;
		}

		pendingProgrammaticSubmitRef.current = true;
		setInput(text);
		inputRef.current = text;
		setTimeout(() => {
			if (generationPhaseRef.current !== "idle") {
				pendingProgrammaticSubmitRef.current = false;
				return;
			}
			formRef.current?.dispatchEvent(
				new Event("submit", { cancelable: true, bubbles: true }),
			);
		}, 50);
	}, []);

	// Toast helper function (defined early for use in hook callbacks)
	const showToastRef = useRef<
		(type: "error" | "success" | "info", message: string) => void
	>(() => {});

	// Voice session hook – single source of truth for all voice state
	const {
		voiceState,
		partialText: realtimePartialText,
		mediaStream: realtimeMediaStream,
		toggle: toggleVoiceSession,
		stop: stopVoiceSession,
		forceSend: voiceForceSend,
		notifyResponseComplete: notifyVoiceResponseComplete,
	} = useVoiceSession({
		onTranscript: (transcript) => {
			// Get current input value from ref to support appending
			const currentInput = inputRef.current.trim();
			const newInput = currentInput
				? `${currentInput} ${transcript}`
				: transcript;

			// Auto-submit via unified helper (sets input + ref + dispatches form submit)
			submitFormProgrammatically(newInput);
		},
		onError: (error) => {
			showToastRef.current("error", t("aiChat.voiceInputError", { error }));
		},
		silenceDurationMs: 800,
		maxRecordingSeconds: 120,
	});

	// Derived booleans for UI convenience
	const voiceSessionActive = voiceState !== "idle";
	const realtimeIsRecording = voiceState === "recording";
	const realtimeIsConnecting = voiceState === "connecting";

	// Pre-compute CSV content mapping: assistant message ID -> most recent CSV from any previous user message
	// Uses O(n) single pass: track the most recent CSV as we iterate forward.
	// Only recalculates when message count changes — CSV attachments are on user messages
	// and never change during streaming (which only appends content to the last assistant message).
	// eslint-disable-next-line react-hooks/exhaustive-deps
	const csvContentMap = useMemo(() => {
		const map = new Map<string, { content: string; fileName: string }>();
		let lastCSV: { content: string; fileName: string } | null = null;

		for (const msg of messages) {
			if (msg.role === "user" && msg.csvAttachments?.length) {
				// Update the most recent CSV
				const csv = msg.csvAttachments[0];
				lastCSV = { content: csv.content, fileName: csv.fileName };
			} else if (msg.role === "assistant" && lastCSV) {
				// Associate this assistant message with the most recent CSV
				map.set(msg.id, lastCSV);
			}
		}
		return map;
	}, [messages.length, messages]);

	const branchSeparatorAfterIndex = useMemo(() => {
		if (!currentConversationMeta?.parent_conversation_id) return null;

		const branchCount = currentConversationMeta.branch_source_message_count;
		if (!branchCount || branchCount < 1) return null;

		const cappedCount = Math.min(branchCount, messages.length);
		for (let i = cappedCount - 1; i >= 0; i -= 1) {
			if (!isMessageHiddenInTimeline(messages[i])) {
				return i;
			}
		}

		return null;
	}, [
		currentConversationMeta?.branch_source_message_count,
		currentConversationMeta?.parent_conversation_id,
		messages,
	]);

	const mapConversationMessages = useCallback(
		(apiMessages: ConversationWithMessages["messages"]): Message[] => {
			return apiMessages.map((msg) => ({
				id: String(msg.id),
				role: msg.role as "user" | "assistant",
				content: msg.content,
				...((
					msg as {
						metadata?: {
							images?: string[];
							artifacts?: MessageArtifacts;
						} | null;
					}
				).metadata?.images?.length
					? {
							images: (
								msg as {
									metadata?: {
										images?: string[];
										artifacts?: MessageArtifacts;
									} | null;
								}
							).metadata?.images,
						}
					: {}),
				...((
					msg as {
						metadata?: {
							images?: string[];
							artifacts?: MessageArtifacts;
						} | null;
					}
				).metadata?.artifacts
					? {
							artifacts: (
								msg as {
									metadata?: {
										images?: string[];
										artifacts?: MessageArtifacts;
									} | null;
								}
							).metadata?.artifacts,
						}
					: {}),
				timestamp: new Date(msg.created_at),
			}));
		},
		[],
	);

	const buildCancelledMessageContent = useCallback(() => {
		return `*${t("aiChat.generationCancelled")}*`;
	}, [t]);

	const buildPendingPatchInferenceCancelPayload = useCallback(() => {
		const conversationId = currentConversationIdRef.current;
		if (!conversationId) return null;

		for (let index = messagesRef.current.length - 1; index >= 0; index -= 1) {
			const message = messagesRef.current[index];
			if (message.role !== "assistant") continue;

			const config = parsePatchInferenceConfig(message.content);
			if (!config) continue;

			const hasActiveRun = [
				config.classification_run,
				config.segmentation_run,
			].some(
				(run) =>
					Boolean(run?.task_id) &&
					(run?.status === "queued" || run?.status === "running"),
			);
			if (!hasActiveRun) continue;

			const messageId = Number(message.id);
			if (!Number.isFinite(messageId) || messageId >= 1000000000) continue;

			return {
				conversationId,
				pending: {
					messageId,
					content: buildCancelledMessageContent(),
					timestamp: Date.now(),
				},
			};
		}

		return null;
	}, [buildCancelledMessageContent]);

	const persistPatchInferenceExitCancellation = useCallback(
		async (
			conversationId: string,
			pending: PendingPatchInferenceCancel,
			keepalive: boolean = false,
		) => {
			await cancelChatPatchInferenceOnExit(
				{
					conversation_id: conversationId,
					message_id: pending.messageId,
					cancel_message: pending.content,
				},
				{ keepalive },
			);
		},
		[],
	);

	const markPendingPatchInferenceCancellationOnExit = useCallback(() => {
		const payload = buildPendingPatchInferenceCancelPayload();
		if (!payload) return;

		const pendingKey = getPendingPatchInferenceCancelKey(
			payload.conversationId,
		);
		const existing = readPendingPatchInferenceCancel(payload.conversationId);
		if (
			!existing ||
			existing.messageId !== payload.pending.messageId ||
			existing.content !== payload.pending.content
		) {
			sessionStorage.setItem(pendingKey, JSON.stringify(payload.pending));
		}

		void persistPatchInferenceExitCancellation(
			payload.conversationId,
			payload.pending,
			true,
		).catch((error) => {
			console.warn(
				"Failed to persist patch inference cancellation on exit:",
				error,
			);
		});
	}, [
		buildPendingPatchInferenceCancelPayload,
		persistPatchInferenceExitCancellation,
	]);

	const markPendingCancelledResponseOnExit = useCallback(() => {
		const conversationId = currentConversationIdRef.current;
		if (!conversationId || generationPhaseRef.current !== "thinking") return;

		const lastMessage = messagesRef.current[messagesRef.current.length - 1];
		if (lastMessage?.role !== "assistant" || lastMessage.content.trim()) return;

		sessionStorage.setItem(
			getPendingCancelledResponseKey(conversationId),
			String(Date.now()),
		);
	}, []);

	const refreshPendingCancelledResponse = useCallback(
		(conversationId: string) => {
			const pendingKey = getPendingCancelledResponseKey(conversationId);

			const runAttempt = (attempt: number) => {
				if (!sessionStorage.getItem(pendingKey)) return;

				const existingTimer =
					pendingCancelledRetryTimersRef.current.get(conversationId);
				if (existingTimer) {
					window.clearTimeout(existingTimer);
				}

				const timerId = window.setTimeout(async () => {
					pendingCancelledRetryTimersRef.current.delete(conversationId);

					if (!sessionStorage.getItem(pendingKey)) return;

					try {
						const latestConversation = await getConversation(conversationId);
						const sortedApiMessages = [...latestConversation.messages].sort(
							(a, b) => a.id - b.id,
						);
						const hasAssistantReply =
							sortedApiMessages[sortedApiMessages.length - 1]?.role ===
							"assistant";

					if (hasAssistantReply) {
						sessionStorage.removeItem(pendingKey);
						if (currentConversationIdRef.current === conversationId) {
							setMessages((prev) =>
								mergeLoadedMessagesWithPendingAssistant(
									mapConversationMessages(sortedApiMessages),
									prev,
									generationPhaseRef.current !== "idle",
								),
							);
						}
						return;
					}
					} catch (error) {
						console.warn(
							"Failed to refresh pending cancelled response:",
							error,
						);
					}

					if (attempt < PENDING_CANCELLED_RESPONSE_MAX_RETRIES) {
						runAttempt(attempt + 1);
					}
				}, PENDING_CANCELLED_RESPONSE_RETRY_DELAY_MS);

				pendingCancelledRetryTimersRef.current.set(conversationId, timerId);
			};

			runAttempt(1);
		},
		[mapConversationMessages],
	);

	const refreshPendingPatchInferenceCancellation = useCallback(
		(conversationId: string) => {
			const pendingKey = getPendingPatchInferenceCancelKey(conversationId);

			const runAttempt = (attempt: number) => {
				if (!sessionStorage.getItem(pendingKey)) return;

				const existingTimer =
					pendingPatchInferenceCancelRetryTimersRef.current.get(conversationId);
				if (existingTimer) {
					window.clearTimeout(existingTimer);
				}

				const timerId = window.setTimeout(async () => {
					pendingPatchInferenceCancelRetryTimersRef.current.delete(
						conversationId,
					);

					const pending = readPendingPatchInferenceCancel(conversationId);
					if (!pending) return;

					try {
						await persistPatchInferenceExitCancellation(
							conversationId,
							pending,
						);
						const latestConversation = await getConversation(conversationId);
						const sortedApiMessages = [...latestConversation.messages].sort(
							(a, b) => a.id - b.id,
						);
						const cancellationPersisted =
							hasPersistedPatchInferenceCancellation(
								sortedApiMessages,
								pending,
							);

						if (cancellationPersisted) {
							sessionStorage.removeItem(pendingKey);
							if (currentConversationIdRef.current === conversationId) {
								setMessages(mapConversationMessages(sortedApiMessages));
							}
							return;
						}
					} catch (error) {
						console.warn(
							"Failed to refresh pending patch inference cancellation:",
							error,
						);
					}

					if (attempt < PENDING_PATCH_INFERENCE_CANCEL_MAX_RETRIES) {
						runAttempt(attempt + 1);
					}
				}, PENDING_PATCH_INFERENCE_CANCEL_RETRY_DELAY_MS);

				pendingPatchInferenceCancelRetryTimersRef.current.set(
					conversationId,
					timerId,
				);
			};

			runAttempt(1);
		},
		[mapConversationMessages, persistPatchInferenceExitCancellation],
	);

	useEffect(() => {
		// Don't scroll to bottom if we're restoring scroll position
		if (scrollRestoredRef.current) {
			scrollRestoredRef.current = false;
			return;
		}
		scrollToBottom();
	}, [scrollToBottom]);

	// Restore conversation from URL (supports page refresh)
	// Also supports legacy sessionStorage restore for backward compatibility
	// biome-ignore lint/correctness/useExhaustiveDependencies: handleLoadConversation is declared after this hook as a non-memoized const; adding it to deps causes a TDZ crash at render time and infinite re-runs — urlConversationId is the only correct trigger
	useEffect(() => {
		// Priority 1: Load from URL if conversationId is present
		if (urlConversationId) {
			// Skip loading if we just created this conversation (to avoid overwriting in-progress messages)
			if (skipConversationLoadRef.current) {
				skipConversationLoadRef.current = false;
				return;
			}
			handleLoadConversation(urlConversationId);
			return;
		}

		// Priority 2: Legacy - restore from sessionStorage (for back navigation from other pages)
		const savedConversationId = sessionStorage.getItem(
			"ai-chat-conversation-id",
		);
		if (savedConversationId) {
			handleLoadConversation(savedConversationId);
			sessionStorage.removeItem("ai-chat-conversation-id");
		}
	}, [urlConversationId]);

	// Restore scroll position after messages are loaded (when returning from another page).
	// Depends on messages.length instead of messages to avoid re-running on every streaming chunk.
	// Scroll restore only matters when message count changes (initial load / conversation switch).
	useEffect(() => {
		const savedScrollPosition = sessionStorage.getItem(
			"ai-chat-scroll-position",
		);
		if (
			savedScrollPosition &&
			messagesContainerRef.current &&
			messages.length > 0
		) {
			// Use requestAnimationFrame to ensure DOM is ready after messages render
			requestAnimationFrame(() => {
				if (messagesContainerRef.current) {
					messagesContainerRef.current.scrollTop = parseInt(
						savedScrollPosition,
						10,
					);
					scrollRestoredRef.current = true;
				}
			});
			sessionStorage.removeItem("ai-chat-scroll-position");
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [messages.length]);

	// Use useLayoutEffect for textarea resize to prevent visual jitter
	// This runs synchronously after DOM updates but before browser paint
	useLayoutEffect(() => {
		// Auto-resize textarea
		if (textareaRef.current) {
			textareaRef.current.style.height = "auto";
			textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
		}
	}, []);

	// Abort any in-progress generation when the component unmounts (e.g., navigating away).
	// This triggers the AbortError catch in executeChatGeneration, which fills the cancel text.
	useEffect(() => {
		const handlePageExit = () => {
			markPendingCancelledResponseOnExit();
			markPendingPatchInferenceCancellationOnExit();
		};

		window.addEventListener("pagehide", handlePageExit);

		return () => {
			handlePageExit();
			window.removeEventListener("pagehide", handlePageExit);
			pendingCancelledRetryTimersRef.current.forEach((timerId) => {
				window.clearTimeout(timerId);
			});
			pendingCancelledRetryTimersRef.current.clear();
			pendingPatchInferenceCancelRetryTimersRef.current.forEach((timerId) => {
				window.clearTimeout(timerId);
			});
			pendingPatchInferenceCancelRetryTimersRef.current.clear();
			abortControllerRef.current?.abort();
		};
	}, [
		markPendingCancelledResponseOnExit,
		markPendingPatchInferenceCancellationOnExit,
	]);

	useEffect(() => {
		const handlePageHide = () => {
			markPendingPatchInferenceCancellationOnExit();
		};

		const handleBeforeLogout = () => {
			markPendingPatchInferenceCancellationOnExit();
		};

		window.addEventListener("pagehide", handlePageHide);
		window.addEventListener(BEFORE_LOGOUT_EVENT, handleBeforeLogout);

		return () => {
			window.removeEventListener("pagehide", handlePageHide);
			window.removeEventListener(BEFORE_LOGOUT_EVENT, handleBeforeLogout);
		};
	}, [markPendingPatchInferenceCancellationOnExit]);

	// Handle initial message from navigation state
	useEffect(() => {
		const state = location.state as {
			initialMessage?: string;
			autoStartRecording?: boolean;
			fromDashboard?: boolean;
		} | null;

		if (state?.initialMessage && !initialMessageSent.current) {
			initialMessageSent.current = true;
			submitFormProgrammatically(state.initialMessage);
		}

		if (state?.autoStartRecording) {
			console.log(
				"[VoiceSession] Auto-start recording triggered from navigation",
			);

			// Clear the autoStartRecording flag immediately to prevent re-triggering
			navigate(location.pathname, {
				replace: true,
				state: { ...state, autoStartRecording: false },
			});

			// Start voice session after a short delay to ensure everything is ready
			setTimeout(() => {
				console.log("[VoiceSession] Starting auto-recording");
				toggleVoiceSession();
			}, 100);
		}
	}, [location, toggleVoiceSession, navigate, submitFormProgrammatically]);

	const setConversationsAndCache = useCallback(
		(nextConversations: Conversation[]) => {
			const normalizedConversations =
				sortConversationsByUpdatedAt(nextConversations);
			setConversations(normalizedConversations);

			if (user?.id) {
				conversationHistoryCache.set(user.id, normalizedConversations);
			}
		},
		[user?.id],
	);

	const updateConversationsAndCache = useCallback(
		(updater: (prevConversations: Conversation[]) => Conversation[]) => {
			setConversations((prevConversations) => {
				const nextConversations = sortConversationsByUpdatedAt(
					updater(prevConversations),
				);

				if (user?.id) {
					conversationHistoryCache.set(user.id, nextConversations);
				}

				return nextConversations;
			});
		},
		[user?.id],
	);

	const loadConversations = useCallback(
		async (options?: { showLoading?: boolean }) => {
			const showLoading = options?.showLoading ?? true;

			try {
				if (showLoading) {
					setIsLoadingConversations(true);
				}

				const convs = await getConversations();
				setConversationsAndCache(convs);
			} catch (error) {
				console.error("Failed to load conversations:", error);
				showToastRef.current("error", t("aiChat.historyLoadFailed"));
			} finally {
				if (showLoading) {
					setIsLoadingConversations(false);
				}
			}
		},
		[setConversationsAndCache, t],
	);

	useEffect(() => {
		if (isAuthLoading) {
			return;
		}

		if (!user?.id) {
			setConversations([]);
			setIsLoadingConversations(false);
			return;
		}

		if (conversationHistoryCache.has(user.id)) {
			setConversations(conversationHistoryCache.get(user.id) ?? []);
			setIsLoadingConversations(false);
			return;
		}

		void loadConversations();
	}, [isAuthLoading, loadConversations, user?.id]);

	const handleNewChat = useCallback(() => {
		setMessages([]);
		setCurrentConversationMeta(null);
		setCurrentConversationId(null);
		untitledBranchConversationIdsRef.current.clear();
		setInput("");
		setImageAttachments([]);
		setFileAttachments([]);
		setShowHistory(false);
		setShowWelcomeHero(true);
		setFeedbacks(new Map());
		setPendingFeedbackIds(new Set());
		setHelpfulnessFeedbacks(new Map());
		setPendingTitleConvIds(new Set());
		// Update URL to base path (remove conversationId from URL)
		if (urlConversationId) {
			navigate("/dashboard", { replace: true });
		}
	}, [navigate, urlConversationId]);

	const handleLoadConversation = async (conversationId: string) => {
		try {
			const conv = await getConversation(conversationId);
			// Sort messages by id to ensure chronological order (defense-in-depth)
			const sortedApiMessages = [...conv.messages].sort((a, b) => a.id - b.id);
			const loadedMessages = mapConversationMessages(sortedApiMessages);
			const pendingCancelledKey =
				getPendingCancelledResponseKey(conversationId);
			const pendingCancelledAt = sessionStorage.getItem(pendingCancelledKey);
			const hasPendingCancelledResponse = Boolean(pendingCancelledAt);
			const pendingPatchInferenceCancel =
				readPendingPatchInferenceCancel(conversationId);
			const pendingPatchInferenceCancelKey =
				getPendingPatchInferenceCancelKey(conversationId);
			const hasAssistantReply =
				sortedApiMessages[sortedApiMessages.length - 1]?.role === "assistant";

			let messagesToShow =
				hasPendingCancelledResponse && !hasAssistantReply
					? [
							...loadedMessages,
							{
								id: `pending-cancelled-${conversationId}`,
								role: "assistant" as const,
								content: buildCancelledMessageContent(),
								timestamp: new Date(Number(pendingCancelledAt) || Date.now()),
							},
						]
					: loadedMessages;

			const pendingCancel = pendingPatchInferenceCancel;
			const hasPersistedPatchInferenceCancel =
				pendingCancel != null &&
				hasPersistedPatchInferenceCancellation(
					sortedApiMessages,
					pendingCancel,
				);

			if (pendingPatchInferenceCancel) {
				if (hasPersistedPatchInferenceCancel) {
					sessionStorage.removeItem(pendingPatchInferenceCancelKey);
				} else {
					messagesToShow = [
						...messagesToShow,
						{
							id: `pending-patch-cancelled-${conversationId}`,
							role: "assistant" as const,
							content: pendingPatchInferenceCancel.content,
							timestamp: new Date(
								pendingPatchInferenceCancel.timestamp || Date.now(),
							),
						},
					];
					refreshPendingPatchInferenceCancellation(conversationId);
				}
			}

			if (hasPendingCancelledResponse) {
				if (hasAssistantReply) {
					sessionStorage.removeItem(pendingCancelledKey);
				} else {
					refreshPendingCancelledResponse(conversationId);
				}
			}

		messagesToShow = messagesToShow.map((msg) => {
			if (msg.role !== "assistant") return msg;
			const rawMsg = sortedApiMessages.find((m) => String(m.id) === msg.id);
			const rawVariants = (rawMsg as { variants?: Array<{ id: number; content: string; created_at: string; is_active_variant: boolean; metadata?: { artifacts?: MessageArtifacts } | null }> })?.variants;
			if (!rawVariants || rawVariants.length <= 1) return msg;
			const activeIdx = rawVariants.findIndex((v) => v.is_active_variant);
			const resolvedActiveIdx = activeIdx >= 0 ? activeIdx : rawVariants.length - 1;
			const activeVariant = rawVariants[resolvedActiveIdx];
			return {
				...msg,
				id: String(activeVariant.id),
				content: activeVariant.content,
				timestamp: new Date(activeVariant.created_at),
				artifacts: activeVariant.metadata?.artifacts,
				regenerations: rawVariants.map((v) => ({
					id: String(v.id),
					content: v.content,
					timestamp: new Date(v.created_at),
					artifacts: v.metadata?.artifacts,
				})),
				activeRegenerationIndex: resolvedActiveIdx,
			};
		});

			const isPlaceholderTitle =
				!conv.title ||
				conv.title === "New Conversation" ||
				conv.title === t("aiChat.newConversation");
			if (conv.parent_conversation_id && isPlaceholderTitle) {
				untitledBranchConversationIdsRef.current.add(conv.conversation_id);
			} else {
				untitledBranchConversationIdsRef.current.delete(conv.conversation_id);
			}

			setMessages((prev) =>
				mergeLoadedMessagesWithPendingAssistant(
					messagesToShow,
					prev,
					generationPhaseRef.current !== "idle",
				),
			);
			setCurrentConversationMeta(conv);
		setCurrentConversationId(conversationId);
		setShowHistory(false);
			setShowWelcomeHero(false);
			setPendingFeedbackIds(new Set());

			// Update URL to reflect the current conversation (for page refresh support)
			if (urlConversationId !== conversationId) {
				navigate(`/dashboard/${conversationId}`, { replace: true });
			}

			// Load feedbacks for this conversation
			try {
				const feedbackList = await getConversationFeedbacks(conversationId);
				const feedbackMap = new Map<number, "thumbs_up" | "thumbs_down">();
				const helpfulnessMap = new Map<number, "helpful" | "not_helpful">();
				for (const fb of feedbackList) {
					if (fb.feedback_type) {
						feedbackMap.set(fb.message_id, fb.feedback_type);
					}
					if (fb.task_helpfulness) {
						helpfulnessMap.set(fb.message_id, fb.task_helpfulness);
					}
				}
				setFeedbacks(feedbackMap);
				setHelpfulnessFeedbacks(helpfulnessMap);
			} catch (error) {
				console.error("Failed to load feedbacks:", error);
				setFeedbacks(new Map());
				setHelpfulnessFeedbacks(new Map());
			}
		} catch (error) {
			console.error("Failed to load conversation:", error);
			setCurrentConversationMeta(null);
			showToastRef.current("error", t("aiChat.conversationLoadFailed"));
			// If loading fails, navigate back to clean URL
			if (urlConversationId) {
				navigate("/dashboard", { replace: true });
			}
		}
	};

	const handleDeleteAllHistory = () => {
		if (conversations.length === 0) return;
		setDeleteConfirmId("all-conversations");
	};

	const handleDeleteConversation = async (
		conversationId: string,
		e: React.MouseEvent,
	) => {
		e.stopPropagation();
		setDeleteConfirmId(conversationId);
	};

	const handleExportConversation = async (
		conversationId: string,
		e: React.MouseEvent,
	) => {
		e.stopPropagation();
		try {
			const conversation = await getConversation(conversationId);

			const lines: string[] = [];
			lines.push(`# ${conversation.title}`);
			lines.push("");
			lines.push(`> Exported: ${new Date().toLocaleString()}`);
			lines.push("");
			lines.push("---");
			lines.push("");

			const visibleMessages = conversation.messages.filter(
				(msg) =>
					!isInternalOnlyMessage(msg.content) && !isPdfContextMessage(msg.content),
			);

			for (const msg of visibleMessages) {
				let roleLabel = msg.role === "user" ? "User" : "Assistant";
				const rawVariants = (msg as { variants?: Array<{ is_active_variant: boolean }> }).variants;
				if (msg.role === "assistant" && rawVariants && rawVariants.length > 1) {
					const activeIdx = rawVariants.findIndex((v) => v.is_active_variant);
					const displayIdx = activeIdx >= 0 ? activeIdx + 1 : rawVariants.length;
					roleLabel = `Assistant (Regeneration ${displayIdx}/${rawVariants.length})`;
				}
					const cleanedContent = cleanMessageContent(msg.content);
					if (!cleanedContent) {
						continue;
					}
				lines.push(`## ${roleLabel}`);
				lines.push("");
					lines.push(cleanedContent);
				lines.push("");
				lines.push("---");
				lines.push("");
			}

			const markdown = lines.join("\n");
			const blob = new Blob([markdown], {
				type: "text/markdown;charset=utf-8",
			});
			const safeTitle = (conversation.title || "conversation")
				.replace(/[\\/:*?"<>|]/g, "_")
				.slice(0, 80);
			downloadBlobFile(blob, `${safeTitle}.md`);
		} catch {
			showToast("error", t("aiChat.exportFailed"));
		}
	};

	const confirmDelete = async () => {
		if (!deleteConfirmId) return;

		try {
			if (deleteConfirmId === "all-conversations") {
				setIsLoadingConversations(true);
				try {
					await Promise.all(
						conversations.map((conv) =>
							deleteConversation(conv.conversation_id),
						),
					);
					setConversationsAndCache([]);
					handleNewChat();
				} catch (error) {
					console.error("Failed to delete all conversations:", error);
				} finally {
					setIsLoadingConversations(false);
				}
			} else {
				await deleteConversation(deleteConfirmId);
				updateConversationsAndCache((prevConversations) =>
					prevConversations.filter(
						(conversation) => conversation.conversation_id !== deleteConfirmId,
					),
				);
				if (currentConversationId === deleteConfirmId) {
					handleNewChat();
				}
			}
		} catch (error) {
			console.error("Failed to delete:", error);
		} finally {
			setDeleteConfirmId(null);
		}
	};

	const cancelDelete = () => {
		setDeleteConfirmId(null);
	};

	// File upload validation constants
	const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
	const MAX_IMAGE_SIZE = 10 * 1024 * 1024; // 10MB
	const MAX_FILES = 10;

	// Check if current model supports image input (reads from shared multimodal models list)
	const currentModel =
		localStorage.getItem("openrouter_model") || "qwen/qwen3.5-plus-02-15";
	const isMultimodalModel = MULTIMODAL_MODELS.has(currentModel);

	// File upload handlers (images, CSV, XLSX)
	const handleFileSelect = async (
		e: React.ChangeEvent<HTMLInputElement> | FileList,
	) => {
		const files = "target" in e ? e.target.files : e;
		if (!files) return;

		// Validate file count
		const totalFiles =
			imageAttachments.length + fileAttachments.length + files.length;
		if (totalFiles > MAX_FILES) {
			showToastRef.current(
				"error",
				t("aiChat.tooManyFiles", { max: MAX_FILES }),
			);
			if ("target" in e && fileInputRef.current)
				fileInputRef.current.value = "";
			return;
		}

		// Validate file sizes
		for (let i = 0; i < files.length; i++) {
			if (files[i].size > MAX_FILE_SIZE) {
				showToastRef.current(
					"error",
					t("aiChat.fileTooLarge", {
						name: files[i].name,
						size: formatFileSize(files[i].size),
						max: formatFileSize(MAX_FILE_SIZE),
					}),
				);
				if ("target" in e && fileInputRef.current)
					fileInputRef.current.value = "";
				return;
			}
		}

		const newImageAttachments: ImageAttachment[] = [];
		const newFileAttachments: FileAttachment[] = [];

		for (let i = 0; i < files.length; i++) {
			const file = files[i];
			const fileName = file.name.toLowerCase();

			// Handle image files
			if (file.type.startsWith("image/")) {
				// Only multimodal models support image input
				if (!isMultimodalModel) {
					showToastRef.current("error", t("aiChat.modelNotMultimodal"));
					if ("target" in e && fileInputRef.current)
						fileInputRef.current.value = "";
					return;
				}
				// Image-specific size limit: 10MB
				if (file.size > MAX_IMAGE_SIZE) {
					showToastRef.current(
						"error",
						t("aiChat.imageTooLarge", {
							name: file.name,
							size: formatFileSize(file.size),
							max: formatFileSize(MAX_IMAGE_SIZE),
						}),
					);
					if ("target" in e && fileInputRef.current)
						fileInputRef.current.value = "";
					return;
				}
				try {
					const base64 = await new Promise<string>((resolve, reject) => {
						const reader = new FileReader();
						reader.onload = () => resolve(reader.result as string);
						reader.onerror = () => reject(reader.error);
						reader.readAsDataURL(file);
					});

					newImageAttachments.push({
						id: `${Date.now()}-${i}`,
						file,
						preview: base64,
						base64,
					});
				} catch {
					showToastRef.current(
						"error",
						t("aiChat.fileReadError", { name: file.name }),
					);
				}
			}
			// Handle CSV files
			else if (fileName.endsWith(".csv") || file.type === "text/csv") {
				try {
					const content = await new Promise<string>((resolve, reject) => {
						const reader = new FileReader();
						reader.onload = () => resolve(reader.result as string);
						reader.onerror = () => reject(reader.error);
						reader.readAsText(file);
					});

					// Parse CSV to get preview (first 5 rows)
					const lines = content.split("\n").filter((line) => line.trim());
					const preview = lines.slice(0, 6); // Header + 5 data rows

					newFileAttachments.push({
						id: `${Date.now()}-${i}`,
						file,
						name: file.name,
						type: "csv",
						content,
						preview,
					});
				} catch {
					showToastRef.current(
						"error",
						t("aiChat.fileReadError", { name: file.name }),
					);
				}
			}
			// Handle XLSX files - parse and convert to CSV
			else if (
				fileName.endsWith(".xlsx") ||
				fileName.endsWith(".xls") ||
				file.type ===
					"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
				file.type === "application/vnd.ms-excel"
			) {
				try {
					const { sheetNames, csv: csvContent } = await xlsxToCSV(
						await file.arrayBuffer(),
					);

					if (sheetNames.length > 1) {
						newFileAttachments.push({
							id: `${Date.now()}-${i}`,
							file,
							name: file.name,
							type: "xlsx",
							content: `__MULTIPLE_SHEETS__:${sheetNames.join(",")}`,
							preview: [
								t("aiChat.excelMultipleSheets", { count: sheetNames.length }),
								...sheetNames.slice(0, 5).map((s) => `  • ${s}`),
								sheetNames.length > 5
									? t("aiChat.excelMoreSheets", {
											count: sheetNames.length - 5,
										})
									: "",
							].filter(Boolean),
						});
					} else {
						const lines = csvContent.split("\n").filter((line) => line.trim());
						const preview = lines.slice(0, 6);
						newFileAttachments.push({
							id: `${Date.now()}-${i}`,
							file,
							name: file.name,
							type: "xlsx",
							content: csvContent,
							preview,
						});
					}
				} catch (error) {
					console.error("Failed to parse XLSX file:", error);
					newFileAttachments.push({
						id: `${Date.now()}-${i}`,
						file,
						name: file.name,
						type: "xlsx",
						content: `__PARSE_ERROR__:${error instanceof Error ? error.message : "Unknown error"}`,
						preview: [t("aiChat.failedToParseExcel", { name: file.name })],
					});
				}
			}
		}

		if (newImageAttachments.length > 0) {
			setImageAttachments((prev) => [...prev, ...newImageAttachments]);
		}
		if (newFileAttachments.length > 0) {
			setFileAttachments((prev) => [...prev, ...newFileAttachments]);
		}

		// Reset file input
		if (fileInputRef.current) {
			fileInputRef.current.value = "";
		}
	};

	const handleImageRemove = (id: string) => {
		setImageAttachments((prev) => prev.filter((img) => img.id !== id));
	};

	const handleFileRemove = (id: string) => {
		setFileAttachments((prev) => prev.filter((f) => f.id !== id));
	};

	// Drag-and-drop handlers for chat area
	const dragCounterRef = useRef(0);
	const handleDragEnter = useCallback((e: React.DragEvent) => {
		e.preventDefault();
		e.stopPropagation();
		dragCounterRef.current++;
		if (e.dataTransfer.types.includes("Files")) {
			setIsDraggingFile(true);
		}
	}, []);

	const handleDragLeave = useCallback((e: React.DragEvent) => {
		e.preventDefault();
		e.stopPropagation();
		dragCounterRef.current--;
		if (dragCounterRef.current === 0) {
			setIsDraggingFile(false);
		}
	}, []);

	const handleDragOver = useCallback((e: React.DragEvent) => {
		e.preventDefault();
		e.stopPropagation();
	}, []);

	const handleDrop = useCallback(
		(e: React.DragEvent) => {
			e.preventDefault();
			e.stopPropagation();
			dragCounterRef.current = 0;
			setIsDraggingFile(false);
			const files = e.dataTransfer.files;
			if (files.length > 0) {
				handleFileSelect(files);
			}
		},
		// biome-ignore lint/correctness/useExhaustiveDependencies: dragCounter/setIsDragging stable, handleFileSelect intentionally excluded
		[handleFileSelect],
	);

	// Native capture-phase drop listener: resets drag overlay even when a child
	// component calls e.stopPropagation() (e.g. DatasetRegistrationCard.handleDrop),
	// which prevents the React synthetic drop event from bubbling to this page.
	// Capture-phase listeners fire before React's synthetic event system, so they
	// always run regardless of stopPropagation in child handlers.
	useEffect(() => {
		const resetDragState = () => {
			dragCounterRef.current = 0;
			setIsDraggingFile(false);
		};
		document.addEventListener("drop", resetDragState, true);
		return () => document.removeEventListener("drop", resetDragState, true);
	}, []);

	// Paste image handler
	useEffect(() => {
		const handlePaste = (e: ClipboardEvent) => {
			const items = e.clipboardData?.items;
			if (!items) return;

			const imageFiles: File[] = [];
			for (let i = 0; i < items.length; i++) {
				if (items[i].type.startsWith("image/")) {
					const file = items[i].getAsFile();
					if (file) imageFiles.push(file);
				}
			}

			if (imageFiles.length > 0) {
				e.preventDefault();
				const dt = new DataTransfer();
				imageFiles.forEach((f) => {
					dt.items.add(f);
				});
				handleFileSelect(dt.files);
			}
		};

		document.addEventListener("paste", handlePaste);
		return () => document.removeEventListener("paste", handlePaste);
		// biome-ignore lint/correctness/useExhaustiveDependencies: handleFileSelect intentionally excluded to avoid re-registering paste listener
	}, [handleFileSelect]);

	const handleScenarioCardClick = (card: (typeof SCENARIO_CARDS)[number]) => {
		setInput(t(card.promptKey));
		setShowWelcomeHero(false);
		// Focus the textarea
		setTimeout(() => textareaRef.current?.focus(), 100);
	};

	// --- Shared chat generation helpers (DRY handleSubmit / handleRegenerate) ---

	/** Build sanitized ChatMessage array from Message[] for the AI API. */
	const buildChatMessages = useCallback(
		(sourceMessages: Message[]): ChatMessage[] => {
			return sourceMessages.map((m) => {
				const sanitizedContent = sanitizeConfigBlocksForAI(m.content);
				if (m.images && m.images.length > 0) {
					const content: ChatMessageContent = [
						{ type: "text" as const, text: sanitizedContent },
						...m.images.map((imgBase64) => ({
							type: "image_url" as const,
							image_url: { url: imgBase64 },
						})),
					];
					return { role: m.role, content };
				}
				return { role: m.role, content: sanitizedContent };
			});
		},
		[],
	);

	/** Execute a chat generation cycle: create AI placeholder → stream → error handling → cleanup. */
	const executeChatGeneration = useCallback(
		async (
			chatMessages: ChatMessage[],
			conversationId: string | undefined,
			options?: {
				onError?: () => void;
				onFinally?: () => void;
				regenerateMessageId?: number;
			},
		) => {
			const aiMessageId = (Date.now() + 1).toString();
			const aiMessage: Message = {
				id: aiMessageId,
				role: "assistant",
				content: "",
				timestamp: new Date(),
			};
			setMessages((prev) => [...prev, aiMessage]);
			setGenerationPhase("thinking");

			if (abortControllerRef.current) {
				abortControllerRef.current.abort();
			}

			const abortController = new AbortController();
			abortControllerRef.current = abortController;
			const currentGenerationId = ++generationIdRef.current;

			// --- Silence timeout: abort if no output chunk received for 60 seconds ---
			const SILENCE_TIMEOUT_MS = 60_000;
			let isTimeoutAbort = false;
			let silenceTimer: ReturnType<typeof setTimeout> | null = null;
			// Slow-document warning: shown after 60 s of continuous PDF downloading/parsing
			let pdfSlowWarningTimer: ReturnType<typeof setTimeout> | null = null;
			let pdfSlowWarningSent = false;

			const startSilenceTimer = () => {
				if (silenceTimer !== null) clearTimeout(silenceTimer);
				silenceTimer = setTimeout(() => {
					isTimeoutAbort = true;
					abortController.abort();
				}, SILENCE_TIMEOUT_MS);
			};

			// Start the timer immediately (covers the "thinking" phase before first chunk)
			startSilenceTimer();

			// --- Chunk batching: accumulate chunks in a buffer, flush via rAF ---
			// This reduces setMessages calls from ~30/s (per-chunk) to ~16/s (per-frame).
			let chunkBuffer = "";
			let rafId: number | null = null;
			// Track the current message ID — it starts as the placeholder ID and gets
			// replaced by the backend-assigned ID when onMessageId fires.  All buffer
			// flushes must use this mutable variable instead of the captured `aiMessageId`
			// so that content isn't lost after an ID rename.
			let trackingId = aiMessageId;

			const flushChunks = () => {
				rafId = null;
				if (!chunkBuffer) return;
				const buffered = chunkBuffer;
				chunkBuffer = "";
				const currentId = trackingId;
				setMessages((prev) => {
					const lastIdx = prev.length - 1;
					if (lastIdx >= 0 && prev[lastIdx].id === currentId) {
						const updated = {
							...prev[lastIdx],
							content: prev[lastIdx].content + buffered,
						};
						const next = [...prev];
						next[lastIdx] = updated;
						return next;
					}
					return prev.map((m) =>
						m.id === currentId ? { ...m, content: m.content + buffered } : m,
					);
				});
			};

			try {
				let hasReceivedContent = false;
				await chatWithAI(
					chatMessages,
					(chunk) => {
						// Reset silence timer on every received chunk
						startSilenceTimer();
						if (!hasReceivedContent) {
							hasReceivedContent = true;
							setGenerationPhase("streaming");
						}
						// Handle __CLEAR_CONTENT__ marker: the backend emits this when a
						// normalize/sanitize transform rewrites the response. Clear the
						// message so the corrected response appears cleanly.
						if (chunk === "__CLEAR_CONTENT__") {
							if (rafId !== null) {
								cancelAnimationFrame(rafId);
								rafId = null;
							}
							const buffered = chunkBuffer;
							chunkBuffer = "";
							const currentId = trackingId;
							setMessages((prev) =>
								prev.map((m) =>
									m.id === currentId
										? {
												...m,
												content: preserveContentOnClearMarker(
													m.content + buffered,
												),
											}
										: m,
								),
							);
							return;
						}
						chunkBuffer += chunk;
						// Schedule a flush on the next animation frame (batches multiple chunks)
						if (rafId === null) {
							rafId = requestAnimationFrame(flushChunks);
						}
					},
					conversationId,
					(messageId) => {
						// Flush any buffered chunks BEFORE renaming the message ID.
						// Without this, rapid-fire content chunks accumulate in chunkBuffer,
						// then onMessageId changes the ID, and the pending flush (or finally
						// block) can no longer find the message — causing blank output.
						if (rafId !== null) {
							cancelAnimationFrame(rafId);
							rafId = null;
						}
						// CRITICAL: Capture trackingId in a const BEFORE any setMessages calls.
						// React 18 batches setMessages updaters — they execute LATER, after
						// `trackingId = newId` below has already run.  If the updater closures
						// reference `trackingId` directly (by-reference), they will see `newId`
						// and fail to find the message (which still has the OLD id).
						// Using a const snapshot ensures the updaters always match the OLD id.
						const oldTrackingId = trackingId;
						if (chunkBuffer) {
							const buffered = chunkBuffer;
							chunkBuffer = "";
							setMessages((prev) =>
								prev.map((m) =>
									m.id === oldTrackingId
										? { ...m, content: m.content + buffered }
										: m,
								),
							);
						}
						const newId = String(messageId);
						setMessages((prev) =>
							prev.map((m) =>
								m.id === oldTrackingId ? { ...m, id: newId } : m,
							),
						);
						trackingId = newId;
					},
					abortController.signal,
					() => {
						// True context-window overflow — append [CONTEXT_LIMIT] block to the AI message
						const contextLimitBlock = "\n\n[CONTEXT_LIMIT][/CONTEXT_LIMIT]";
						const currentTrackingId = trackingId;
						setMessages((prev) =>
							prev.map((m) =>
								m.id === currentTrackingId
									? { ...m, content: m.content + contextLimitBlock }
									: m,
							),
						);
					},
					() => {
						// Output was truncated — append [RESPONSE_TRUNCATED] block to the AI message
						const responseTruncatedBlock =
							"\n\n[RESPONSE_TRUNCATED][/RESPONSE_TRUNCATED]";
						const currentTrackingId = trackingId;
						setMessages((prev) =>
							prev.map((m) =>
								m.id === currentTrackingId
									? { ...m, content: m.content + responseTruncatedBlock }
									: m,
							),
						);
					},
					(pdfContext) => {
						const hiddenContent = `[PDF_CONTEXT]\n${pdfContext}\n[/PDF_CONTEXT]`;
						const hiddenMessage: Message = {
							id: `pdfctx-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
							role: "user",
							content: hiddenContent,
							timestamp: new Date(),
						};
						const currentTrackingId = trackingId;
						setMessages((prev) => {
							if (
								prev.some(
									(m) => m.role === "user" && m.content === hiddenContent,
								)
							) {
								return prev;
							}
							const assistantIndex = prev.findIndex(
								(m) => m.id === currentTrackingId,
							);
							if (assistantIndex === -1) {
								return [...prev, hiddenMessage];
							}
							return [
								...prev.slice(0, assistantIndex),
								hiddenMessage,
								...prev.slice(assistantIndex),
							];
						});
					},
					(event) => {
						const currentId = trackingId;
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== currentId) return m;
								const prev_search = m.artifacts?.search;
								return {
									...m,
									artifacts: {
										...m.artifacts,
										search: {
											statuses: [...(prev_search?.statuses ?? []), event],
											phase: "searching",
											pdfStatuses: prev_search?.pdfStatuses ?? [],
											webSearchResults: prev_search?.webSearchResults ?? [],
											pdfParseResults: prev_search?.pdfParseResults ?? [],
										},
									},
								};
							}),
						);
					},
					(event) => {
						// PDF heartbeat events keep the connection alive — reset the silence timer
						// so large-document parsing doesn't trigger a false timeout abort.
						startSilenceTimer();
						// Start the slow-document notice timer on the first downloading/parsing event.
						if (
							!pdfSlowWarningSent &&
							pdfSlowWarningTimer === null &&
							(event.status === "downloading" || event.status === "parsing")
						) {
							pdfSlowWarningTimer = setTimeout(() => {
								pdfSlowWarningTimer = null;
								pdfSlowWarningSent = true;
								showToastRef.current(
									"info",
									t("aiChat.pdfLargeDocumentSlowNotice"),
								);
							}, 60_000);
						}
						const currentId = trackingId;
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== currentId) return m;
								const prev_search = m.artifacts?.search;
								return {
									...m,
									artifacts: {
										...m.artifacts,
										search: {
											statuses: prev_search?.statuses ?? [],
											phase: prev_search?.phase ?? "idle",
											pdfStatuses: [...(prev_search?.pdfStatuses ?? []), event],
											webSearchResults: prev_search?.webSearchResults ?? [],
											pdfParseResults: prev_search?.pdfParseResults ?? [],
										},
									},
								};
							}),
						);
					},
					() => {
						const currentId = trackingId;
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== currentId) return m;
								const prev_search = m.artifacts?.search;
								if (!prev_search) return m;
								return {
									...m,
									artifacts: {
										...m.artifacts,
										search: { ...prev_search, phase: "summarizing" },
									},
								};
							}),
						);
					},
					(event: WebSearchResultEvent) => {
						const currentId = trackingId;
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== currentId) return m;
								const prev_search = m.artifacts?.search;
								return {
									...m,
									artifacts: {
										...m.artifacts,
										search: {
											statuses: prev_search?.statuses ?? [],
											phase: prev_search?.phase ?? "idle",
											pdfStatuses: prev_search?.pdfStatuses ?? [],
											webSearchResults: [
												...(prev_search?.webSearchResults ?? []),
												event,
											],
											pdfParseResults: prev_search?.pdfParseResults ?? [],
										},
									},
								};
							}),
						);
					},
					(event: PdfParseResultEvent) => {
						const currentId = trackingId;
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== currentId) return m;
								const prev_search = m.artifacts?.search;
								const existing = prev_search?.pdfParseResults ?? [];
								const updated = existing.some((p) => p.url === event.url)
									? existing.map((p) => (p.url === event.url ? event : p))
									: [...existing, event];
								return {
									...m,
									artifacts: {
										...m.artifacts,
										search: {
											statuses: prev_search?.statuses ?? [],
											phase: prev_search?.phase ?? "idle",
											pdfStatuses: prev_search?.pdfStatuses ?? [],
											webSearchResults: prev_search?.webSearchResults ?? [],
											pdfParseResults: updated,
										},
									},
								};
							}),
						);
					},
					() => {
						// search_clear: backend signals that a search/read_article tool was
						// invoked after text was already streamed. Preserve the pre-search text
						// (flush any buffered chunks into it) so it isn't lost.
						if (rafId !== null) {
							cancelAnimationFrame(rafId);
							rafId = null;
						}
						const buffered = chunkBuffer;
						chunkBuffer = "";
					const currentId = trackingId;
					setMessages((prev) =>
						prev.map((m) =>
							m.id === currentId
								? { ...m, content: m.content + buffered }
								: m,
						),
					);
				},
				options?.regenerateMessageId,
			);
		} catch (error) {
			if (error instanceof DOMException && error.name === "AbortError") {
				if (isTimeoutAbort) {
					console.log("AI generation timed out (no output for 60 seconds)");
						// Fill timed-out message with i18n text (append if partial content exists)
						const timeoutText = t("aiChat.generationTimeout");
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== trackingId) return m;
								const content = m.content
									? `${m.content}\n\n---\n\n*${timeoutText}*`
									: `*${timeoutText}*`;
								return { ...m, content };
							}),
						);
					} else {
						console.log("AI generation stopped by user");
						// Fill cancelled message with i18n text (append if partial content exists)
						const cancelText = t("aiChat.generationCancelled");
						setMessages((prev) =>
							prev.map((m) => {
								if (m.id !== trackingId) return m;
								const content = m.content
									? `${m.content}\n\n---\n\n*${cancelText}*`
									: `*${cancelText}*`;
								return { ...m, content };
							}),
						);
					}
				} else {
					console.error("Failed to get AI response:", error);
					setMessages((prev) =>
						prev.map((m) =>
							m.id === trackingId
								? { ...m, content: m.content || t("aiChat.aiErrorFallback") }
								: m,
						),
					);
				}
				options?.onError?.();
			} finally {
				// Clear silence timer
				if (silenceTimer !== null) {
					clearTimeout(silenceTimer);
					silenceTimer = null;
				}
				// Clear slow-document warning timer
				if (pdfSlowWarningTimer !== null) {
					clearTimeout(pdfSlowWarningTimer);
					pdfSlowWarningTimer = null;
				}
				// Flush any remaining buffered chunks before finishing
				if (rafId !== null) {
					cancelAnimationFrame(rafId);
					rafId = null;
				}
				if (chunkBuffer) {
					const remaining = chunkBuffer;
					chunkBuffer = "";
					setMessages((prev) =>
						prev.map((m) =>
							m.id === trackingId
								? { ...m, content: m.content + remaining }
								: m,
						),
					);
				}
				if (generationIdRef.current === currentGenerationId) {
					setGenerationPhase("idle");
					const doneTrackingId = trackingId;
					setMessages((prev) =>
						prev.map((m) => {
							if (m.id !== doneTrackingId) return m;
							const prev_search = m.artifacts?.search;
							if (!prev_search) return m;
							return {
								...m,
								artifacts: {
									...m.artifacts,
									search: { ...prev_search, phase: "done" },
								},
							};
						}),
					);
					abortControllerRef.current = null;

					// Persist the final message content (including cancel/error text) to backend.
					// Use setTimeout(0) to let the setMessages updates above flush first,
					// then read the latest content from messagesRef.
					if (conversationId) {
						// Capture trackingId for the async closure
						const finalTrackingId = trackingId;
						setTimeout(async () => {
							const finalMsg = messagesRef.current.find(
								(m) => m.id === finalTrackingId,
							);
							if (!finalMsg || !finalMsg.content) return;
							const numericId = parseInt(finalTrackingId, 10);
							const isBackendId =
								!Number.isNaN(numericId) && numericId < 1000000000;
							try {
								if (isBackendId) {
									await updateMessage(
										conversationId,
										numericId,
										finalMsg.content,
										finalMsg.artifacts ?? undefined,
									);
								} else {
									const saved = await addMessage(
										conversationId,
										"assistant",
										finalMsg.content,
									);
									setMessages((prev) =>
										prev.map((m) =>
											m.id === finalTrackingId
												? { ...m, id: String(saved.id) }
												: m,
										),
									);
								}
							} catch (err) {
								console.warn("Failed to persist cancelled/error message:", err);
							}
						}, 0);
					}

					options?.onFinally?.();
				}
			}
		},
		[t],
	);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		pendingProgrammaticSubmitRef.current = false;
		// Use inputRef.current to get the latest value, avoiding stale closure issues
		// when form is submitted programmatically (e.g., from voice transcription)
		const currentInputValue = inputRef.current.trim();
		if (
			(!currentInputValue &&
				imageAttachments.length === 0 &&
				fileAttachments.length === 0) ||
			isGenerating
		)
			return;

		// Build user message content with optional file info
		let messageContent = currentInputValue;

		// Append file attachment info to message content for AI to analyze
		if (fileAttachments.length > 0) {
			const fileInfos = fileAttachments
				.map((f) => {
					// Check for special error/warning markers in XLSX content
					if (
						f.type === "xlsx" &&
						f.content.startsWith("__MULTIPLE_SHEETS__:")
					) {
						const sheets = f.content.replace("__MULTIPLE_SHEETS__:", "");
						return t("aiChat.uploadedExcelWarning", { name: f.name, sheets });
					} else if (
						f.type === "xlsx" &&
						f.content.startsWith("__PARSE_ERROR__:")
					) {
						const error = f.content.replace("__PARSE_ERROR__:", "");
						return t("aiChat.uploadedExcelError", { name: f.name, error });
					} else {
						// Both CSV and successfully parsed XLSX (converted to CSV)
						// Use [CSV_PREVIEW] block for beautiful rendering
						const totalRows = f.content
							.split("\n")
							.filter((line) => line.trim()).length;
						const previewData = {
							fileName: f.name,
							fileType: f.type,
							preview: f.preview,
							totalRows: totalRows,
						};
						return `\n\n[CSV_PREVIEW]${JSON.stringify(previewData)}[/CSV_PREVIEW]`;
					}
				})
				.join("");
			messageContent += fileInfos;
		}

		// Build user message with optional images and CSV attachments
		// Include both CSV files and successfully parsed XLSX files (which now contain CSV content)
		const currentImages = imageAttachments.map((img) => img.base64);
		const csvAttachments = fileAttachments
			.filter((f) => {
				// Include CSV files and XLSX files that were successfully converted (no error markers)
				if (f.type === "csv") return true;
				if (
					f.type === "xlsx" &&
					!f.content.startsWith("__MULTIPLE_SHEETS__:") &&
					!f.content.startsWith("__PARSE_ERROR__:")
				)
					return true;
				return false;
			})
			.map((f) => ({ fileName: f.name, content: f.content }));
		const userMessage: Message = {
			id: Date.now().toString(),
			role: "user",
			content: messageContent,
			images: currentImages.length > 0 ? currentImages : undefined,
			csvAttachments: csvAttachments.length > 0 ? csvAttachments : undefined,
			timestamp: new Date(),
		};

		setShowWelcomeHero(false);
		// Reset scroll lock so auto-scroll follows the new response
		userScrolledAwayRef.current = false;
		setHasScrolledAway(false);
		setMessages((prev) => [...prev, userMessage]);
		setInput("");
		setImageAttachments([]); // Clear attachments after sending
		setFileAttachments([]); // Clear file attachments after sending

		// Create a new conversation if this is the first user message
		let conversationId = currentConversationId;
		let isNewConversation = false;
		let pendingNavigationConversationId: string | null = null;
		if (!conversationId && messages.length === 0) {
			try {
				const newConv = await createConversation(t("aiChat.newConversation"));
				conversationId = newConv.conversation_id;
				isNewConversation = true;
				setCurrentConversationMeta(newConv);
				setCurrentConversationId(conversationId);
					setPendingTitleConvIds((prev) => new Set(prev).add(newConv.conversation_id));
				updateConversationsAndCache((prevConversations) =>
					upsertConversation(prevConversations, newConv),
				);
				pendingNavigationConversationId = conversationId;
			} catch (error) {
				console.error("Failed to create conversation:", error);
			}
		}

			const isPlaceholderTitle = (title?: string | null) =>
				!title ||
				title === "New Conversation" ||
				title === t("aiChat.newConversation");

			const isUntitledBranchConversation =
				conversationId != null &&
				(
					untitledBranchConversationIdsRef.current.has(conversationId) ||
					(Boolean(currentConversationMeta?.parent_conversation_id) &&
						currentConversationMeta?.conversation_id === conversationId &&
						isPlaceholderTitle(currentConversationMeta?.title))
				);

			const shouldGenerateTitleAfterReply =
				Boolean(conversationId) &&
				(isNewConversation || isUntitledBranchConversation);

			if (conversationId && shouldGenerateTitleAfterReply) {
				setPendingTitleConvIds((prev) => new Set(prev).add(conversationId));
			}

		// Build chat messages and execute generation with shared helper
		const chatMessages = buildChatMessages(messages.concat([userMessage]));
		await executeChatGeneration(chatMessages, conversationId || undefined, {
			onError: () => stopVoiceSession(),
			onFinally: () => {
				if (pendingNavigationConversationId) {
					skipConversationLoadRef.current = true;
					navigate(`/dashboard/${pendingNavigationConversationId}`, {
						replace: true,
					});
				}

				// Check for SUBMIT_TASK and CANCEL_TASK_NOW blocks in ALL cases (voice or text input)
				setTimeout(() => {
					const latestMessages = messagesRef.current;
					const lastMessage = latestMessages[latestMessages.length - 1];
					if (lastMessage?.role === "assistant") {
						if (parseSubmitTask(lastMessage.content)) {
							setSubmitTaskTrigger((prev) => prev + 1);
						}
						if (parseCancelTaskNow(lastMessage.content)) {
							setCancelTaskTrigger((prev) => prev + 1);
						}
					}
				}, 100);

				// Notify voice session that LLM response is complete
				setTimeout(() => {
					const latestMessages = messagesRef.current;
					const lastMessage = latestMessages[latestMessages.length - 1];
					const aiContent =
						lastMessage?.role === "assistant" ? lastMessage.content : "";
					notifyVoiceResponseComplete(aiContent);
				}, 150);

					if (shouldGenerateTitleAfterReply && conversationId) {
					generateConversationTitle(conversationId)
						.then((result) => {
								untitledBranchConversationIdsRef.current.delete(conversationId);
								setCurrentConversationMeta((prev) =>
									prev && prev.conversation_id === conversationId
										? { ...prev, title: result.title }
										: prev,
								);
							updateConversationsAndCache((prev) => {
								const updated = prev.map((c) =>
									c.conversation_id === conversationId
										? { ...c, title: result.title }
										: c,
								);
								// If conversation not in cache yet, add it
								if (!updated.some((c) => c.conversation_id === conversationId)) {
									updated.push({
										conversation_id: conversationId,
										user_id: user?.id || "",
										title: result.title,
										created_at: new Date().toISOString(),
										updated_at: new Date().toISOString(),
									});
								}
								return updated;
							});
						})
						.catch(() => {
							const fallbackTitle =
								userMessage.content.length > 20
									? `${userMessage.content.substring(0, 20)}...`
									: userMessage.content || t("aiChat.imageAnalysis");
								untitledBranchConversationIdsRef.current.delete(conversationId);
								setCurrentConversationMeta((prev) =>
									prev && prev.conversation_id === conversationId
										? { ...prev, title: fallbackTitle }
										: prev,
								);
							updateConversationsAndCache((prev) =>
								prev.map((c) =>
									c.conversation_id === conversationId
										? { ...c, title: fallbackTitle }
										: c,
								),
							);
						})
						.finally(() => {
							setPendingTitleConvIds((prev) => {
								const next = new Set(prev);
								next.delete(conversationId);
								return next;
							});
						});
				}
			},
		});
	};

	const handleKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			handleSubmit(e);
		}
	};

	// Toast helper function
	const showToast = useCallback(
		(type: "error" | "success" | "info", message: string) => {
			setToastMessage({ type, message });
			setTimeout(() => setToastMessage(null), 5000);
		},
		[],
	);

	// Adapter for AssistantMessage onToast prop (object signature → auto-dismiss)
	const handleToast = useCallback(
		(toast: { type: "error" | "success" | "info"; message: string }) => {
			showToast(toast.type, toast.message);
		},
		[showToast],
	);

	// Update ref for use in hook callbacks
	showToastRef.current = showToast;

	const handleBranchConversation = useCallback(async () => {
		if (!currentConversationId || isGenerating) return;

		try {
				const branchedConversation = await createConversation(
					t("aiChat.newConversation"),
					{ sourceConversationId: currentConversationId },
				);
				untitledBranchConversationIdsRef.current.add(
					branchedConversation.conversation_id,
				);

			updateConversationsAndCache((prevConversations) =>
				upsertConversation(prevConversations, branchedConversation),
			);

			await handleLoadConversation(branchedConversation.conversation_id);
			showToast("success", t("aiChat.branchConversationCreated"));
		} catch (error) {
			console.error("Failed to branch conversation:", error);
			showToast("error", t("aiChat.branchConversationFailed"));
		}
	}, [
		currentConversationId,
		handleLoadConversation,
		isGenerating,
		showToast,
		t,
		updateConversationsAndCache,
	]);

	// --- Persistence helpers (DRY the repeated persist-to-backend patterns) ---

	/** Persist an existing message's content update to backend (update pattern). */
	const persistMessageUpdate = useCallback(
		async (
			messageId: string,
			updatedContent: string,
			errorToastKey?: string,
		) => {
			if (!currentConversationId) return;
			const numericId = parseInt(messageId, 10);
			const isBackendId = !Number.isNaN(numericId) && numericId < 1000000000;
			if (!isBackendId) {
				console.warn(
					`Skipping persistence for temporary message ID: ${messageId}`,
				);
				return;
			}
			try {
				await updateMessage(currentConversationId, numericId, updatedContent);
			} catch (error) {
				console.warn("Failed to persist message update to backend:", error);
				if (errorToastKey) {
					showToast("error", t(errorToastKey));
				}
			}
		},
		[currentConversationId, showToast, t],
	);

	const replaceMessageContent = useCallback(
		async (
			messageId: string,
			updatedContent: string,
			errorToastKey?: string,
		) => {
			setMessages((prev) =>
				prev.map((message) =>
					message.id === messageId
						? { ...message, content: updatedContent }
						: message,
				),
			);
			await persistMessageUpdate(messageId, updatedContent, errorToastKey);
		},
		[persistMessageUpdate],
	);

	/** Add a new assistant message to backend and remap its local ID (add+remap pattern). */
	const persistNewAssistantMessage = useCallback(
		async (localMessageId: string, content: string) => {
			if (!currentConversationId) return;
			try {
				const savedMessage = await addMessage(
					currentConversationId,
					"assistant",
					content,
				);
				setMessages((prev) =>
					prev.map((m) =>
						m.id === localMessageId ? { ...m, id: String(savedMessage.id) } : m,
					),
				);
			} catch (error) {
				console.warn(
					"Failed to persist new assistant message to backend:",
					error,
				);
			}
		},
		[currentConversationId],
	);

	// Clean message content by removing special markup blocks
	const cleanMessageContent = useCallback((content: string): string => {
		let cleaned = content;
		cleaned = removeOptionsBlock(cleaned);
		cleaned = removeTaskConfigBlock(cleaned);
		cleaned = removeImageRecommendationBlock(cleaned);
		cleaned = removeCSVActionBlock(cleaned);
		cleaned = removeNavigateBlock(cleaned);
		cleaned = removeCSVPreviewBlock(cleaned);
		cleaned = removeMetricConfigBlock(cleaned);
		cleaned = removeChartConfigBlock(cleaned);
		cleaned = removeQuickAnalysisConfigBlock(cleaned);
		// Remove VOICE_CONTROL block - it's for internal use only
		cleaned = removeVoiceControlBlock(cleaned);
		cleaned = removeModelListBlock(cleaned);
		cleaned = removePatchInferenceBlock(cleaned);
		// Remove CONTEXT_LIMIT block - UI-only warning card
		cleaned = removeContextLimitBlock(cleaned);
		// Remove RESPONSE_TRUNCATED block - UI-only warning card
		cleaned = removeResponseTruncatedBlock(cleaned);
			cleaned = removeInternalMetadataBlocks(cleaned);
		return cleaned.trim();
	}, []);

	// Copy message content to clipboard (cleaned of special markup)
	const handleCopy = useCallback(
		async (content: string) => {
			try {
				const cleanedContent = cleanMessageContent(content);
				if (navigator.clipboard?.writeText) {
					await navigator.clipboard.writeText(cleanedContent);
				} else {
					// Fallback for Electron or non-secure contexts
					const textArea = document.createElement("textarea");
					textArea.value = cleanedContent;
					textArea.style.position = "fixed";
					textArea.style.opacity = "0";
					document.body.appendChild(textArea);
					textArea.select();
					document.execCommand("copy");
					document.body.removeChild(textArea);
				}
				showToast("success", t("aiChat.copiedToClipboard"));
			} catch (error) {
				console.error("Failed to copy:", error);
				showToast("error", t("aiChat.failedToCopy"));
			}
		},
		[cleanMessageContent, showToast, t],
	);

	const deleteConversationBranchFromMessage = useCallback(
		async (messageId: string): Promise<boolean> => {
			if (!currentConversationId) return true;

			const persistedMessageId = getPersistedMessageId(messageId);
			if (persistedMessageId === null) {
				return true;
			}

			try {
				await deleteMessagesFrom(currentConversationId, persistedMessageId);
				return true;
			} catch (error) {
				console.error("Failed to delete messages from backend:", error);
				showToast("error", t("aiChat.failedToDeleteMessage"));
				return false;
			}
		},
		[currentConversationId, showToast, t],
	);

	const resolveReplayContext = useCallback(
		(messageIndex: number) => {
			const currentMessages = messagesRef.current;
			const targetMessage = currentMessages[messageIndex];
			if (!targetMessage) return null;

			const userMessageIndex =
				targetMessage.role === "user" ? messageIndex : messageIndex - 1;
			const userMessage = currentMessages[userMessageIndex];

			if (userMessageIndex < 0 || userMessage?.role !== "user") {
				showToast("error", t("aiChat.cannotRegenerate"));
				return null;
			}

			if (!hasReplayableAttachmentData(userMessage)) {
				showToast("error", t("aiChat.cannotResubmitMissingFiles"));
				return null;
			}

			return {
				currentMessages,
				targetMessage,
				userMessage,
				userMessageIndex,
			};
		},
		[showToast, t],
	);

	// Handle thumbs up/down feedback for a message
	const handleFeedback = useCallback(
		async (messageId: string, feedbackType: "thumbs_up" | "thumbs_down") => {
			const numericId = getPersistedMessageId(messageId);
			if (numericId === null) {
				showToast("error", t("aiChat.invalidMessageId"));
				return;
			}

			if (pendingFeedbackIds.has(numericId)) {
				return;
			}

			const currentFeedback = feedbacks.get(numericId);

			// Get message content and context for preservation (use ref to avoid stale closure)
			const currentMessages = messagesRef.current;
			const messageIndex = currentMessages.findIndex((m) => m.id === messageId);
			let messageContent: string | null = null;
			let contextMessages:
				| { role: "user" | "assistant"; content: string }[]
				| null = null;

			if (messageIndex >= 0) {
				const currentMessage = currentMessages[messageIndex];
				messageContent = currentMessage.content;

				// Get previous message for context (if exists)
				if (messageIndex > 0) {
					const prevMessage = currentMessages[messageIndex - 1];
					contextMessages = [
						{
							role: prevMessage.role,
							content: prevMessage.content,
						},
					];
				}
			}

			// Optimistic update: Update UI immediately
			if (currentFeedback === feedbackType) {
				// Toggle off - remove feedback
				setFeedbacks((prev) => {
					const newMap = new Map(prev);
					newMap.delete(numericId);
					return newMap;
				});
			} else {
				// Set new feedback
				setFeedbacks((prev) => {
					const newMap = new Map(prev);
					newMap.set(numericId, feedbackType);
					return newMap;
				});
			}

			// Then submit to backend in background
			setPendingFeedbackIds((prev) => {
				const next = new Set(prev);
				next.add(numericId);
				return next;
			});

			try {
				if (currentFeedback === feedbackType) {
					await submitMessageFeedback(numericId, null);
				} else {
					await submitMessageFeedback(
						numericId,
						feedbackType,
						undefined, // taskHelpfulness
						undefined, // relatedTaskId
						undefined, // timeToActionSeconds
						messageContent,
						contextMessages,
					);
				}
			} catch (error) {
				console.error("Failed to submit feedback:", error);
				// Rollback: Revert UI state on error
				if (currentFeedback === feedbackType) {
					// Was trying to toggle off, restore the feedback
					setFeedbacks((prev) => {
						const newMap = new Map(prev);
						newMap.set(numericId, feedbackType);
						return newMap;
					});
				} else {
					// Was trying to set new feedback, revert to previous state
					setFeedbacks((prev) => {
						const newMap = new Map(prev);
						if (currentFeedback) {
							newMap.set(numericId, currentFeedback);
						} else {
							newMap.delete(numericId);
						}
						return newMap;
					});
				}
				showToast("error", t("aiChat.failedToSubmitFeedback"));
			} finally {
				setPendingFeedbackIds((prev) => {
					const next = new Set(prev);
					next.delete(numericId);
					return next;
				});
			}
		},
		[feedbacks, pendingFeedbackIds, showToast, t],
	);

	// Format timestamp for display
	const formatTimestamp = (date: Date): string => {
		const now = new Date();
		const diffMs = now.getTime() - date.getTime();
		const diffMins = Math.floor(diffMs / 60000);
		const diffHours = Math.floor(diffMs / 3600000);
		const diffDays = Math.floor(diffMs / 86400000);

		if (diffMins < 1) return t("aiChat.justNow");
		if (diffMins < 60) return t("aiChat.minutesAgo", { count: diffMins });
		if (diffHours < 24) return t("aiChat.hoursAgo", { count: diffHours });
		if (diffDays < 7) return t("aiChat.daysAgo", { count: diffDays });

		return date.toLocaleDateString(undefined, {
			month: "short",
			day: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		});
	};

	// Handle helpfulness feedback for task submission
	const handleHelpfulnessFeedback = useCallback(
		async (
			messageId: string,
			helpfulness: "helpful" | "not_helpful",
			relatedTaskId: string,
			taskType?: "training" | "inference" | "analysis" | "registration",
			taskTitle?: string,
		) => {
			const numericId = parseInt(messageId, 10);
			if (Number.isNaN(numericId)) {
				showToast("error", t("aiChat.invalidMessageId"));
				return;
			}

			// Calculate time from FIRST message in conversation to current time (feedback submission)
			let timeToActionSeconds: number | null = null;
			const currentMessages = messagesRef.current;

			if (currentMessages.length > 0) {
				const firstMessageTime = currentMessages[0].timestamp.getTime();
				const now = Date.now();
				timeToActionSeconds = (now - firstMessageTime) / 1000;
			}

			// Update local helpfulness feedbacks state for persistence display
			setHelpfulnessFeedbacks((prev) => {
				const newMap = new Map(prev);
				newMap.set(numericId, helpfulness);
				return newMap;
			});

			try {
				await submitMessageFeedback(
					numericId,
					undefined, // feedbackType
					helpfulness,
					relatedTaskId,
					timeToActionSeconds,
					undefined, // messageContent (not needed for task feedback)
					undefined, // contextMessages (not needed for task feedback)
					taskType ?? undefined,
					taskTitle ?? undefined,
				);
			} catch (error) {
				console.error("Failed to submit helpfulness feedback:", error);
				// Rollback on error
				setHelpfulnessFeedbacks((prev) => {
					const newMap = new Map(prev);
					newMap.delete(numericId);
					return newMap;
				});
				showToast("error", t("aiChat.failedToSubmitFeedback"));
			}
		},
		[showToast, t],
	);

	// Delete a message and all subsequent messages (for branching)
	const handleDeleteMessage = useCallback(
		async (messageIndex: number) => {
			if (isGenerating) return;

			const currentMessages = messagesRef.current;
			const targetMessage = currentMessages[messageIndex];
			if (!targetMessage) return;

			if (!(await deleteConversationBranchFromMessage(targetMessage.id))) {
				return;
			}

			const newMessages = currentMessages.slice(0, messageIndex);
			setMessages(newMessages);
			showToast("info", t("aiChat.messageDeleted"));
		},
		[deleteConversationBranchFromMessage, isGenerating, showToast, t],
	);

	const handleRegenerate = useCallback(
		async (messageIndex: number) => {
			if (isGenerating) return;

			const replayContext = resolveReplayContext(messageIndex);
			if (!replayContext) return;

			const aiMessage = replayContext.targetMessage;
			if (aiMessage.role !== "assistant") return;

			const persistedAiId = getPersistedMessageId(aiMessage.id);
			if (!persistedAiId) return;

			const existingVariants: RegenerationVariant[] = aiMessage.regenerations ?? [];
			const savedVariants: RegenerationVariant[] =
				existingVariants.length === 0
					? [
							{
								id: aiMessage.id,
								content: aiMessage.content,
								timestamp: aiMessage.timestamp,
								artifacts: aiMessage.artifacts,
							},
						]
					: existingVariants;

			const messagesUpToUser = replayContext.currentMessages.slice(
				0,
				messageIndex,
			);
			setShowWelcomeHero(false);
			userScrolledAwayRef.current = false;
			setHasScrolledAway(false);
			setMessages(messagesUpToUser);

			const chatMessages = buildChatMessages(messagesUpToUser);
			await executeChatGeneration(chatMessages, currentConversationId || undefined, {
				regenerateMessageId: persistedAiId,
				onFinally: () => {
					setMessages((prev) => {
						if (prev.length === 0) return prev;
						const newAiMsg = prev[prev.length - 1];
						if (newAiMsg.role !== "assistant") return prev;

						const allVariants: RegenerationVariant[] = [
							...savedVariants,
							{
								id: newAiMsg.id,
								content: newAiMsg.content,
								timestamp: newAiMsg.timestamp,
								artifacts: newAiMsg.artifacts,
							},
						];
						const newActiveIndex = allVariants.length - 1;

						const mergedAiMsg: Message = {
							...newAiMsg,
							regenerations: allVariants,
							activeRegenerationIndex: newActiveIndex,
						};
						return [...prev.slice(0, -1), mergedAiMsg];
					});
				},
			});
		},
		[
			buildChatMessages,
			currentConversationId,
			executeChatGeneration,
			isGenerating,
			resolveReplayContext,
		],
	);

	const handleNavigateVariant = useCallback(
		(messageIndex: number, direction: "prev" | "next") => {
			const convId = currentConversationIdRef.current;

			setMessages((prev) =>
				prev.map((msg, i) => {
					if (
						i !== messageIndex ||
						!msg.regenerations ||
						msg.regenerations.length <= 1
					)
						return msg;

					const total = msg.regenerations.length;
					const current = msg.activeRegenerationIndex ?? total - 1;
					const newIndex =
						direction === "prev"
							? Math.max(0, current - 1)
							: Math.min(total - 1, current + 1);

					if (newIndex === current) return msg;

					const activeVariant = msg.regenerations[newIndex];

					const targetId = getPersistedMessageId(activeVariant.id);
					if (convId && targetId) {
						activateMessageVariant(convId, targetId).catch(console.error);
					}

					return {
						...msg,
						id: activeVariant.id,
						content: activeVariant.content,
						timestamp: activeVariant.timestamp,
						artifacts: activeVariant.artifacts,
						activeRegenerationIndex: newIndex,
					};
				}),
			);
		},
		[],
	);

	// Stop AI generation and voice recording
	const handleStopGeneration = useCallback(() => {
		abortControllerRef.current?.abort();
		stopVoiceSession();
	}, [stopVoiceSession]);

	// Handle option button selection - auto-send message
	const handleOptionSelect = useCallback(
		(text: string) => {
			submitFormProgrammatically(text);
		},
		[submitFormProgrammatically],
	);

	// Handle task submission success
	const handleTaskSubmitSuccess = useCallback(
		async (taskId: string, messageId: string) => {
			// Update the original message's TASK_CONFIG block to include submitted_task_id
			// This persists the submission status so it's preserved when reloading the conversation

			// Find the message in current state (use ref to avoid stale closure)
			const currentMessages = messagesRef.current;
			const messageIndex = currentMessages.findIndex((m) => m.id === messageId);
			if (messageIndex === -1 && currentMessages.length > 0) {
				console.warn(`Message ${messageId} not found for task update`);
			}

			// Compute updated content from ref, then update state and persist
			let updatedContent: string | null = null;
			const currentMessage = currentMessages.find((m) => m.id === messageId);
			if (currentMessage) {
				updatedContent = currentMessage.content.replace(
					/\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/,
					(_match, json) => {
						try {
							const config = JSON.parse(json.trim());
							config.submitted_task_id = taskId;
							return `[TASK_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_CONFIG]`;
						} catch {
							return _match;
						}
					},
				);
			}

			if (updatedContent) {
				const finalContent = updatedContent;
				setMessages((prev) =>
					prev.map((m) =>
						m.id === messageId ? { ...m, content: finalContent } : m,
					),
				);
				// Persist in background - don't block navigation
				persistMessageUpdate(
					messageId,
					updatedContent,
					"aiChat.failedToSaveTaskStatus",
				).catch(console.error);
			}

			// Add a success message with navigation card to the chat
			const navigateBlock = JSON.stringify(
				{
					target: `/task/${taskId}`,
					buttonTextKey: "aiChat.taskSuccess.viewTrainingProgress",
					descriptionKey: "aiChat.taskSuccess.trainingSubmittedDesc",
					type: "task",
					taskId: taskId,
				},
				null,
				2,
			);
			const successContent = `${t("aiChat.taskSuccess.trainingCreated")}\n\n[NAVIGATE]\n${navigateBlock}\n[/NAVIGATE]`;
			const successMessage: Message = {
				id: Date.now().toString(),
				role: "assistant",
				content: successContent,
				timestamp: new Date(),
			};
			setMessages((prev) => [...prev, successMessage]);
			showToast("success", t("chatComponents.taskConfig.taskCreatedSuccess"));

			// Don't navigate — stay on the chat page (fire-and-forget).
			// The success message already contains a NAVIGATE card for the user to click if they want.

			// Persist success message in background
			persistNewAssistantMessage(successMessage.id, successContent).catch(
				console.error,
			);
		},
		[persistMessageUpdate, persistNewAssistantMessage, showToast, t],
	);

	// Handle registration success (persist to message history)
	const handleRegistrationSuccess = useCallback(
		async (
			taskId: string,
			fileCount: number,
			datasetName: string,
			mode: "existing" | "new",
			messageId?: string,
		) => {
			if (!messageId) return;

			// Find the message from ref to avoid stale closure
			const currentMessages = messagesRef.current;
			const messageIndex = currentMessages.findIndex((m) => m.id === messageId);
			if (messageIndex === -1 && currentMessages.length > 0) {
				console.warn(`Message ${messageId} not found for registration update`);
			}

			// Compute updated content from ref, then update state and persist
			let updatedContent: string | null = null;
			const currentMessage = currentMessages.find((m) => m.id === messageId);
			if (currentMessage) {
				updatedContent = currentMessage.content.replace(
					/\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/,
					(_match, json) => {
						try {
							const config = JSON.parse(json.trim());
							config.submitted_task_id = taskId;
							config.submitted_file_count = fileCount;
							config.submitted_dataset_name = datasetName;
							config.submitted_mode = mode;
							return `[DATASET_REGISTRATION]\n${JSON.stringify(config, null, 2)}\n[/DATASET_REGISTRATION]`;
						} catch {
							return _match;
						}
					},
				);
			}

			if (updatedContent) {
				const finalContent = updatedContent;
				setMessages((prev) =>
					prev.map((m) =>
						m.id === messageId ? { ...m, content: finalContent } : m,
					),
				);
				await persistMessageUpdate(
					messageId,
					updatedContent,
					"aiChat.failedToSaveRegistrationStatus",
				);
			}

			showToast("info", t("aiChat.registrationStarted"));

			// Auto-send message to trigger AI's STEP 6 response (METADATA_UPLOAD card)
			const autoMessage = t("aiChat.registrationAutoMessage", {
				count: fileCount,
			});
			submitFormProgrammatically(autoMessage);
		},
		[persistMessageUpdate, showToast, submitFormProgrammatically, t],
	);

	// Handle metadata upload success (persist upload_result to message history)
	const handleMetadataUploadSuccess = useCallback(
		async (
			result: import("../api").UploadSplitsResponse,
			_datasetId: string,
			messageId?: string,
		) => {
			if (!messageId) return;

			// Compute updated content from ref, then update state and persist
			let updatedContent: string | null = null;
			const currentMessage = messagesRef.current.find(
				(m) => m.id === messageId,
			);
			if (currentMessage) {
				updatedContent = currentMessage.content.replace(
					/\[METADATA_UPLOAD\]([\s\S]*?)\[\/METADATA_UPLOAD\]/,
					(_match, json) => {
						try {
							const config = JSON.parse(json.trim());
							config.upload_result = {
								updated_count: result.updated_count,
								not_found_count: result.not_found_count,
								auto_val_count: result.auto_val_count,
							};
							return `[METADATA_UPLOAD]\n${JSON.stringify(config, null, 2)}\n[/METADATA_UPLOAD]`;
						} catch {
							return _match;
						}
					},
				);
			}

			if (updatedContent) {
				const finalContent = updatedContent;
				setMessages((prev) =>
					prev.map((m) =>
						m.id === messageId ? { ...m, content: finalContent } : m,
					),
				);
				await persistMessageUpdate(
					messageId,
					updatedContent,
					"aiChat.failedToSaveMetadataStatus",
				);
			}

			showToast(
				"success",
				t("aiChat.metadataUploaded", { count: result.updated_count }),
			);
		},
		[persistMessageUpdate, showToast, t],
	);

	// Handle task submission error
	const handleTaskSubmitError = useCallback(
		(error: string) => {
			// Show prominent error toast so user is immediately aware of the failure
			showToast("error", error);
			// Also pre-fill input to let user send the error to AI for analysis
			const errorMessage = t("aiChat.taskSubmitErrorMessage", { error });
			setInput(errorMessage);
		},
		[showToast, t],
	);

	// Handle analysis submission success (internal or external)
	const handleInternalAnalysisSubmitSuccess = useCallback(
		async (taskId: string, analysisId: string, messageId: string) => {
			// Determine if this is external validation (analysisId is empty for external)
			const isExternalValidation = !analysisId;

			// Update the original message's ANALYSIS_CONFIG block (use ref to avoid stale closure)
			let updatedContent: string | null = null;
			const currentMessage = messagesRef.current.find(
				(m) => m.id === messageId,
			);
			if (currentMessage) {
				updatedContent = currentMessage.content.replace(
					/\[ANALYSIS_CONFIG\]([\s\S]*?)\[\/ANALYSIS_CONFIG\]/,
					(_match, json) => {
						try {
							const config = JSON.parse(json.trim());
							if (analysisId) {
								config.submitted_analysis_id = analysisId;
							} else {
								// External validation - store the task_id
								config.external_validation_task_id = taskId;
							}
							return `[ANALYSIS_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/ANALYSIS_CONFIG]`;
						} catch {
							return _match;
						}
					},
				);
			}

			if (updatedContent) {
				const finalContent = updatedContent;
				setMessages((prev) =>
					prev.map((m) =>
						m.id === messageId ? { ...m, content: finalContent } : m,
					),
				);
				await persistMessageUpdate(
					messageId,
					updatedContent,
					"aiChat.failedToSaveAnalysisStatus",
				);
			}

			const successContent = isExternalValidation
				? `${t("aiChat.taskSuccess.externalValidationStarted", { taskId })}\n\n[NAVIGATE]\n${JSON.stringify(
						{
							target: `/task/${taskId}`,
							buttonTextKey: "aiChat.taskSuccess.viewResults",
							descriptionKey: "aiChat.taskSuccess.validationResultsDesc",
						},
						null,
						2,
					)}\n[/NAVIGATE]`
				: `${t("aiChat.taskSuccess.analysisCompleted")}\n\n[NAVIGATE]\n${JSON.stringify(
						{
							target: "/results",
							state: { selectedTaskId: taskId },
							buttonTextKey: "aiChat.taskSuccess.viewAnalysisResults",
							descriptionKey: "aiChat.taskSuccess.analysisResultsDesc",
						},
						null,
						2,
					)}\n[/NAVIGATE]`;

			const successMessage: Message = {
				id: Date.now().toString(),
				role: "assistant",
				content: successContent,
				timestamp: new Date(),
			};
			setMessages((prev) => [...prev, successMessage]);

			await persistNewAssistantMessage(successMessage.id, successContent);
		},
		[persistMessageUpdate, persistNewAssistantMessage, t],
	);

	// Handle task history data loaded - persist cached tasks to message content
	const handleTaskHistoryDataLoaded = useCallback(
		async (data: CachedTaskData[], messageId: string) => {
			// Find the message from ref to avoid stale closure
			const currentMessage = messagesRef.current.find(
				(m) => m.id === messageId,
			);
			if (!currentMessage) return;

			const updatedContent = currentMessage.content.replace(
				/\[TASK_HISTORY_CONFIG\]([\s\S]*?)\[\/TASK_HISTORY_CONFIG\]/,
				(_match, json) => {
					try {
						const config = JSON.parse(json.trim());
						config.cached_tasks = data;
						config.cached_at = new Date().toISOString();
						return `[TASK_HISTORY_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_HISTORY_CONFIG]`;
					} catch {
						return _match;
					}
				},
			);

			// Update local state
			setMessages((prev) =>
				prev.map((m) =>
					m.id === messageId ? { ...m, content: updatedContent } : m,
				),
			);

			// Persist to backend
			await persistMessageUpdate(messageId, updatedContent);
		},
		[persistMessageUpdate],
	);

	// Do not persist quick-analysis payloads into message content.
	// Analysis visibility must always be revalidated against current backend permissions.
	const handleQuickAnalysisDataLoaded = useCallback(
		(_data: CachedAnalysisData, _messageId: string) => {},
		[],
	);

	return (
		<section
			aria-label={t("aiChat.chatRegion")}
			className="relative flex h-full overflow-hidden border border-t-0 border-[color:var(--surface-border)] bg-[color:var(--surface-base)] shadow-[var(--shadow-soft)]"
			onDragEnter={handleDragEnter}
			onDragLeave={handleDragLeave}
			onDragOver={handleDragOver}
			onDrop={handleDrop}
		>
			{/* Drag-and-drop overlay */}
			{isDraggingFile && (
				<div className="absolute inset-0 z-50 bg-primary-500/10 backdrop-blur-[2px] flex items-center justify-center border-4 border-primary-500 border-dashed rounded-xl pointer-events-none">
					<div className="bg-white px-8 py-4 rounded-full shadow-xl font-bold text-primary-600 flex items-center gap-3">
						<Paperclip className="w-6 h-6" />
						{t("aiChat.dropFilesHere")}
					</div>
				</div>
			)}

			{/* Mobile sidebar overlay backdrop */}
			{showHistory && (
				<button
					type="button"
					aria-label={t("aiChat.closeSidebar")}
					className="fixed top-16 inset-x-0 bottom-0 bg-black/20 z-30 lg:hidden backdrop-blur-sm transition-opacity cursor-default"
					onClick={() => setShowHistory(false)}
				/>
			)}

			{/* Gemini-style Sidebar - always rendered, inline on desktop, overlay on mobile */}
			{/* Mobile: always fixed + translate-x slide (never participates in flex layout) */}
			{/* Desktop: inline flex child with width animation */}
			<nav
				className={`flex flex-col overflow-hidden border-r border-[color:var(--surface-border)] bg-[color:var(--surface-work)]/94 backdrop-blur-xl
          fixed top-16 bottom-0 left-0 z-40 w-72 transition-transform duration-300 ease-in-out
          ${showHistory ? "translate-x-0" : "-translate-x-full"}
          lg:relative lg:top-auto lg:bottom-auto lg:z-auto lg:flex-shrink-0 lg:translate-x-0 lg:transition-all
          ${showHistory ? "lg:w-72" : "lg:w-14"}
        `}
				aria-label={t("aiChat.history")}
			>
				{/* Sidebar Top Icons - hidden on mobile (header hamburger handles it) */}
					<div
						className={getSidebarToggleBarClassName(showHistory)}
					>
					<Tooltip
						content={
							showHistory
								? t("aiChat.closeChatHistory")
								: t("aiChat.openChatHistory")
						}
					>
						<button
							type="button"
							onClick={() => setShowHistory(!showHistory)}
							className="flex-shrink-0 rounded-full border border-transparent p-2 text-slate-500 transition-colors hover:border-[color:var(--surface-border)] hover:bg-white/85 hover:text-slate-950"
						>
							<Menu className="w-5 h-5" />
						</button>
					</Tooltip>
				</div>

				{/* Expanded sidebar content - always rendered, fade in/out with opacity */}
				<div
					className={`w-[268px] min-w-[268px] flex flex-col flex-1 overflow-hidden transition-opacity duration-300 ease-in-out ${showHistory ? "opacity-100" : "opacity-0 pointer-events-none"}`}
				>
					{/* New Research Task Button */}
					<div className="px-3 pb-3 pt-4 lg:pt-3">
						<button
							type="button"
							onClick={handleNewChat}
							className="flex w-full items-center justify-center gap-2 rounded-[1.1rem] border border-primary-500/80 bg-primary-600 px-4 py-3 text-sm font-semibold text-white shadow-[var(--shadow-soft)] transition-all hover:-translate-y-0.5 hover:bg-primary-700 hover:shadow-[var(--shadow-elevated)]"
						>
							<Plus className="w-4 h-4" />
							{t("aiChat.newResearchTask")}
						</button>
					</div>

					{/* Tools Section */}
					<div className="border-b border-[color:var(--surface-border)] px-3 pb-2 pt-1">
						<div className="flex items-center gap-2 px-2 mb-2">
							<Wrench className="w-4 h-4 text-gray-400" />
							<h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
								{t("aiChat.sidebar.tools")}
							</h3>
						</div>
						<div className="space-y-0.5">
							<button
								type="button"
								onClick={() => {
									navigate("/register");
									setShowHistory(false);
								}}
							className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-700 transition-colors hover:bg-orange-50/80 hover:text-orange-700"
							>
								<Plus className="w-4 h-4 text-orange-500 group-hover:text-orange-600" />
								<span className="flex-1 text-left">
									{t("aiChat.sidebar.registerData")}
								</span>
								<ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-orange-400 opacity-0 group-hover:opacity-100 transition-all" />
							</button>
							<button
								type="button"
								onClick={() => {
									navigate("/wsi-list");
									setShowHistory(false);
								}}
							className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-700 transition-colors hover:bg-blue-50/80 hover:text-blue-700"
							>
								<Database className="w-4 h-4 text-blue-500 group-hover:text-blue-600" />
								<span className="flex-1 text-left">
									{t("aiChat.sidebar.dataRepository")}
								</span>
								<ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
							</button>
							<button
								type="button"
								onClick={() => {
									navigate("/task-list");
									setShowHistory(false);
								}}
							className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-700 transition-colors hover:bg-violet-50/80 hover:text-violet-700"
							>
							<ClipboardList className="w-4 h-4 text-violet-500 group-hover:text-violet-600" />
								<span className="flex-1 text-left">
									{t("aiChat.sidebar.analysisLab")}
								</span>
								<ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-violet-400 opacity-0 group-hover:opacity-100 transition-all" />
							</button>
							<button
								type="button"
								onClick={() => {
									navigate("/tools");
									setShowHistory(false);
								}}
							className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-700 transition-colors hover:bg-emerald-50/80 hover:text-emerald-700"
							>
							<Wrench className="w-4 h-4 text-emerald-500 group-hover:text-emerald-600" />
								<span className="flex-1 text-left">
									{t("aiChat.sidebar.insightsReports")}
								</span>
								<ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-emerald-400 opacity-0 group-hover:opacity-100 transition-all" />
							</button>
						</div>
					</div>

					{/* History Section */}
					<div className="flex items-center justify-between px-5 pt-3 pb-1">
						<div className="flex items-center gap-2">
							<History className="w-4 h-4 text-gray-400" />
							<h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
								{t("aiChat.history")}
							</h3>
						</div>
						{conversations.length > 0 && (
							<Tooltip content={t("aiChat.deleteAllHistory")}>
								<button
									type="button"
									onClick={handleDeleteAllHistory}
									className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
								>
									<Trash2 className="w-4 h-4" />
								</button>
							</Tooltip>
						)}
					</div>

					<div className="flex-1 overflow-y-auto p-3">
						{isLoadingConversations ? (
							<div className="flex flex-col items-center justify-center py-12">
								<Loader2 className="w-8 h-8 text-primary-500 animate-spin mb-3" />
								<p className="text-sm text-gray-500">
									{t("aiChat.loadingConversations")}
								</p>
							</div>
						) : conversations.length === 0 ? (
							<div className="flex flex-col items-center justify-center py-12 text-center">
								<div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-3">
									<MessageSquare className="w-8 h-8 text-gray-300" />
								</div>
								<p className="text-sm font-medium text-gray-900 mb-1">
									{t("aiChat.noConversationsYet")}
								</p>
								<p className="text-xs text-gray-500">
									{t("aiChat.startNewChat")}
								</p>
							</div>
						) : (
							<div className="space-y-2">
								{conversations.map((conv) => (
									<div
										key={conv.conversation_id}
										className={`group relative rounded-xl transition-all border ${
											currentConversationId === conv.conversation_id
												? "bg-primary-50 border-primary-200 shadow-sm"
												: "hover:bg-gray-50 border-transparent hover:border-gray-100"
										}`}
									>
										<button
											type="button"
											className="w-full p-3 text-left cursor-pointer"
											onClick={() =>
												handleLoadConversation(conv.conversation_id)
											}
										>
											<div className="flex items-start justify-between gap-2">
												<div className="flex-1 min-w-0">
															<div className="flex items-center gap-1.5 mb-1 min-w-0">
																{conv.parent_conversation_id && (
																	<Tooltip content={t("aiChat.branchConversation")}>
																		<span
																			className={`inline-flex items-center justify-center rounded-md p-1 ${
																				currentConversationId === conv.conversation_id
																					? "bg-violet-100 text-violet-700"
																					: "bg-violet-50 text-violet-600"
																			}`}
																		>
																			<BranchForkIcon className="w-3.5 h-3.5" />
																		</span>
																	</Tooltip>
																)}
																<h3
																	className={`text-sm font-medium truncate min-w-0 ${
																		currentConversationId === conv.conversation_id
																			? "text-primary-900"
																			: "text-gray-900"
																	}`}
																>
																	{pendingTitleConvIds.has(conv.conversation_id) ? (
																		<div className="h-4 w-24 rounded bg-gray-200 animate-pulse" />
																	) : (
																		conv.title
																	)}
																</h3>
															</div>
													<div className="flex items-center gap-1 text-xs text-gray-500">
														<Clock className="w-3 h-3" />
														{new Date(conv.updated_at).toLocaleDateString([], {
															month: "short",
															day: "numeric",
															hour: "2-digit",
															minute: "2-digit",
														})}
													</div>
												</div>
												<div className="flex items-center gap-0.5 flex-shrink-0">
													<Tooltip content={t("aiChat.exportConversation")}>
														<button
															type="button"
															onClick={(e) =>
																handleExportConversation(
																	conv.conversation_id,
																	e,
																)
															}
															className="sm:opacity-0 sm:group-hover:opacity-100 p-1.5 text-gray-400 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-all"
														>
															<Share2 className="w-4 h-4" />
														</button>
													</Tooltip>
													<Tooltip content={t("aiChat.deleteConversation")}>
														<button
															type="button"
															onClick={(e) =>
																handleDeleteConversation(
																	conv.conversation_id,
																	e,
																)
															}
															className="sm:opacity-0 sm:group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
														>
															<Trash2 className="w-4 h-4" />
														</button>
													</Tooltip>
												</div>
											</div>
										</button>
									</div>
								))}
							</div>
						)}
					</div>
				</div>
			</nav>

			{/* Main Chat Area */}
			<div className="relative z-10 flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-[linear-gradient(180deg,rgba(255,255,255,0.16)_0%,rgba(255,255,255,0.04)_100%)]">
				<div
					ref={messagesContainerRef}
					data-chat-messages-container
					data-current-conversation-id={currentConversationId || ""}
					className="flex-1 overflow-y-auto custom-scrollbar"
					role="log"
					aria-label={t("aiChat.chatMessages")}
					aria-live="polite"
				>
					<div className="px-4 pb-40 pt-6 sm:px-6 lg:px-8">
						<div className="mx-auto max-w-4xl space-y-6">
							{/* Gemini-style Welcome Hero with Scenario Cards */}
							{messages.length === 0 && showWelcomeHero && (
								<div className="flex min-h-[calc(100vh-16rem)] flex-col items-center justify-center space-y-4 pb-12 pt-6 text-center">
									{/* Hero Title */}
									<div className="space-y-1.5 sm:space-y-2">
										<div className="flex items-center justify-center gap-2 mb-1 sm:mb-2">
										<div className="flex h-11 w-11 items-center justify-center rounded-[1.35rem] border border-primary-300/60 bg-gradient-to-br from-primary-500 to-primary-700 shadow-[var(--shadow-elevated)] sm:h-12 sm:w-12">
												<Sparkles className="w-5 h-5 sm:w-7 sm:h-7 text-white" />
											</div>
										</div>
										<h1 className="bg-gradient-to-r from-slate-950 via-slate-700 to-slate-950 bg-clip-text text-xl font-semibold tracking-[-0.04em] text-transparent sm:text-3xl md:text-4xl">
											{t("aiChat.welcomeTitle")}
										</h1>
										<p className="mx-auto max-w-xl text-sm leading-7 text-slate-500 sm:text-base">
											{t("aiChat.welcomeDescription")}
										</p>
									</div>

									{/* Scenario Cards */}
									<div className="mt-2 grid w-full max-w-2xl grid-cols-2 gap-2 sm:gap-3">
										{SCENARIO_CARDS.map((card) => {
											const Icon = card.icon;
											return (
												<button
													type="button"
													key={card.id}
													onClick={() => handleScenarioCardClick(card)}
													className={`${card.bgColor} group rounded-[1.35rem] border border-white/70 p-3 text-left shadow-[var(--shadow-soft)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-elevated)] sm:p-4`}
												>
													<div className="flex items-start gap-2.5 sm:gap-3">
														<div
														className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-white/80 bg-white/90 shadow-[var(--shadow-soft)] transition-shadow group-hover:shadow-[var(--shadow-elevated)] sm:h-9 sm:w-9`}
														>
															<Icon className={`w-4 h-4 ${card.iconColor}`} />
														</div>
														<div className="min-w-0">
															<h3 className="mb-0.5 text-xs font-semibold tracking-[-0.02em] text-slate-950 sm:text-sm">
																{t(card.titleKey)}
															</h3>
															<p className="text-xs leading-snug text-slate-600">
																{t(card.descriptionKey)}
															</p>
														</div>
													</div>
												</button>
											);
										})}
									</div>
								</div>
							)}
							{/* Find the last message with a TaskConfigCard/CancelTaskCard to only pass triggers to it */}
							{(() => {
								// Find the index of the last message that contains a TaskConfigCard
								let lastTaskConfigIndex = -1;
								let lastCancelTaskIndex = -1;
								for (let i = messages.length - 1; i >= 0; i--) {
									const msg = messages[i];
									if (msg.role === "assistant") {
										if (
											lastTaskConfigIndex === -1 &&
											parseTaskConfig(msg.content)
										) {
											lastTaskConfigIndex = i;
										}
										if (
											lastCancelTaskIndex === -1 &&
											parseCancelTaskConfig(msg.content)
										) {
											lastCancelTaskIndex = i;
										}
										// Stop if both found
										if (
											lastTaskConfigIndex !== -1 &&
											lastCancelTaskIndex !== -1
										) {
											break;
										}
									}
								}
								return messages.map((message, index) => {
										if (isMessageHiddenInTimeline(message)) {
										return null;
									}
									return (
											<Fragment key={message.id}>
												<div
														className={`group flex items-start gap-4 ${message.role === "user" ? "flex-row-reverse" : "flex-row"}`}
												>
											{/* Avatar */}
											<div className="flex-shrink-0 mt-1">
												<div
															className={`hidden h-8 w-8 items-center justify-center rounded-full border shadow-[var(--shadow-soft)] ${
														message.role === "user"
															? "bg-white border-gray-100"
															: "bg-white border-gray-100"
													}`}
												>
													{message.role === "user" ? (
														<User className="w-5 h-5 text-gray-600" />
													) : (
														<Bot className="w-5 h-5 text-primary-600" />
													)}
												</div>
											</div>

											{/* Message Content */}
											<div
															className={`flex max-w-[80%] min-w-0 flex-1 flex-col ${message.role === "user" ? "items-end" : "items-start"}`}
											>
												{/* User Images */}
												{message.role === "user" &&
													message.images &&
													message.images.length > 0 && (
														<div className="flex flex-wrap gap-2 mb-2 justify-end">
															{message.images.map((img, idx) => (
																<img
																	key={img}
																	src={img}
																	alt={t("aiChat.attachmentAlt", {
																		index: idx + 1,
																	})}
																	className="max-w-[200px] max-h-[200px] rounded-xl object-cover border border-gray-200 shadow-sm"
																/>
															))}
														</div>
													)}

												{/* Message Bubble */}
												<div
															className={`relative w-full overflow-hidden px-5 py-3.5 text-[15px] leading-7 shadow-[var(--shadow-soft)] ${
																message.role === "user"
																	? "rounded-[22px] rounded-tr-md border border-primary-400/60 bg-gradient-to-br from-primary-500 to-primary-700 text-white selection:bg-white/30"
																	: "rounded-[22px] rounded-tl-md border border-[color:var(--surface-border)] bg-[color:var(--surface-elevated)] text-slate-900"
															}`}
												>
													{message.role === "user" ? (
														(() => {
															// Parse CSV preview from user message
															const csvPreview = parseCSVPreview(
																message.content,
															);
															const displayContent = csvPreview
																? removeCSVPreviewBlock(message.content)
																: message.content;

															return (
																<div>
																	{displayContent.trim() && (
																		<div className="whitespace-pre-wrap break-words">
																			{displayContent}
																		</div>
																	)}
																	{csvPreview && (
																		<CSVPreviewCard {...csvPreview} />
																	)}
																</div>
															);
														})()
												) : message.content === "" ? (
													isGenerating && index === messages.length - 1 ? (
														// When search artifacts exist (PDF downloading/parsing, web search),
														// render AssistantMessage so status cards are visible even before text arrives.
														message.artifacts?.search ? (
															(() => {
																const referenceImages = (() => {
																	for (let i = index - 1; i >= 0; i -= 1) {
																		const candidate = messages[i];
																		if (candidate.role === "user" && candidate.images?.length) {
																			return candidate.images;
																		}
																	}
																	return [] as string[];
																})();
																return (
																	<AssistantMessage
																		content={message.content}
																		messageId={message.id}
																		onOptionSelect={handleOptionSelect}
																		onTaskSubmitSuccess={handleTaskSubmitSuccess}
																		onInternalAnalysisSubmitSuccess={handleInternalAnalysisSubmitSuccess}
																		onTaskSubmitError={handleTaskSubmitError}
																		onTaskHistoryDataLoaded={handleTaskHistoryDataLoaded}
																		onQuickAnalysisDataLoaded={handleQuickAnalysisDataLoaded}
																		onHelpfulnessFeedback={handleHelpfulnessFeedback}
																		savedHelpfulnessFeedback={helpfulnessFeedbacks.get(parseInt(message.id, 10)) || null}
																		isStreaming={isGenerating && index === messages.length - 1}
																		isLoading={isGenerating}
																		csvContent={csvContentMap.get(message.id)?.content}
																		csvFileName={csvContentMap.get(message.id)?.fileName}
																		onToast={handleToast}
																		onRegistrationSuccess={handleRegistrationSuccess}
																		onMetadataUploadSuccess={handleMetadataUploadSuccess}
																		submitTaskTrigger={index === lastTaskConfigIndex ? submitTaskTrigger : undefined}
																		cancelTaskTrigger={index === lastCancelTaskIndex ? cancelTaskTrigger : undefined}
																		onNewChat={handleNewChat}
																		conversationId={currentConversationId || undefined}
																		referenceImages={referenceImages}
																		onMessageContentReplace={replaceMessageContent}
																		searchArtifacts={message.artifacts ?? null}
																	/>
																);
															})()
														) : (
															// ChatGPT-like Thinking Indicator with staggered bouncing dots
															<div
																className="flex items-center gap-2.5 py-2"
																aria-busy="true"
															>
																<div
																	className="flex items-center gap-1"
																	aria-hidden="true"
																>
																	<div
																		className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
																		style={{
																			animationDelay: "0ms",
																			animationDuration: "1.2s",
																		}}
																	/>
																	<div
																		className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
																		style={{
																			animationDelay: "200ms",
																			animationDuration: "1.2s",
																		}}
																	/>
																	<div
																		className="w-2 h-2 bg-primary-400 rounded-full animate-bounce"
																		style={{
																			animationDelay: "400ms",
																			animationDuration: "1.2s",
																		}}
																	/>
																</div>
																<span className="text-sm font-medium text-gray-400">
																	{t("aiChat.thinking")}
																</span>
															</div>
														)
													) : (
														<div className="py-2 text-sm text-gray-400">
															{t("aiChat.aiErrorFallback")}
														</div>
													)
												) : (
														(() => {
															const referenceImages = (() => {
																for (let i = index - 1; i >= 0; i -= 1) {
																	const candidate = messages[i];
																	if (
																		candidate.role === "user" &&
																		candidate.images?.length
																	) {
																		return candidate.images;
																	}
																}
																return [] as string[];
															})();
															return (
																<AssistantMessage
																	content={message.content}
																	messageId={message.id}
																	onOptionSelect={handleOptionSelect}
																	onTaskSubmitSuccess={handleTaskSubmitSuccess}
																	onInternalAnalysisSubmitSuccess={
																		handleInternalAnalysisSubmitSuccess
																	}
																	onTaskSubmitError={handleTaskSubmitError}
																	onTaskHistoryDataLoaded={
																		handleTaskHistoryDataLoaded
																	}
																	onQuickAnalysisDataLoaded={
																		handleQuickAnalysisDataLoaded
																	}
																	onHelpfulnessFeedback={
																		handleHelpfulnessFeedback
																	}
																	savedHelpfulnessFeedback={
																		helpfulnessFeedbacks.get(
																			parseInt(message.id, 10),
																		) || null
																	}
																	// "Streaming" 表示当前这条助手消息还在生成中（不管是否已经收到首个 chunk），
																	// 用 isGenerating 而不是 isLoading，这样在 Exa 搜索阶段（只收到 SEARCH_STATUS/WEB_SEARCH_RESULT）
																	// 也会触发搜索状态卡片和 skeleton，避免出现中间一大块空白。
																	isStreaming={
																		isGenerating &&
																		index === messages.length - 1
																	}
																	isLoading={isGenerating}
																	csvContent={
																		csvContentMap.get(message.id)?.content
																	}
																	csvFileName={
																		csvContentMap.get(message.id)?.fileName
																	}
																	onToast={handleToast}
																	onRegistrationSuccess={
																		handleRegistrationSuccess
																	}
																	onMetadataUploadSuccess={
																		handleMetadataUploadSuccess
																	}
																	submitTaskTrigger={
																		index === lastTaskConfigIndex
																			? submitTaskTrigger
																			: undefined
																	}
																	cancelTaskTrigger={
																		index === lastCancelTaskIndex
																			? cancelTaskTrigger
																			: undefined
																	}
																	onNewChat={handleNewChat}
																	conversationId={
																		currentConversationId || undefined
																	}
																	referenceImages={referenceImages}
																	onMessageContentReplace={
																		replaceMessageContent
																	}
																	searchArtifacts={message.artifacts ?? null}
																/>
															);
														})()
													)}
												</div>

												{/* Timestamp & Actions for Assistant Messages */}
												{message.role === "assistant" &&
													message.content !== "" && (
														<div className="flex items-center gap-3 mt-2 text-gray-400">
															{(() => {
																const isLatestVariant =
																	!message.regenerations ||
																	message.activeRegenerationIndex ===
																		message.regenerations.length - 1;
																const persistedMessageId = isLatestVariant
																	? getPersistedMessageId(message.id)
																	: null;
																const feedbackPending =
																	persistedMessageId !== null &&
																	pendingFeedbackIds.has(persistedMessageId);
																const activeIdx =
																	message.activeRegenerationIndex ??
																	(message.regenerations
																		? message.regenerations.length - 1
																		: 0);
																	const isLatestAssistantMessage = !messages
																		.slice(index + 1)
																		.some((nextMessage) => nextMessage.role === "assistant");
																return (
																	<>
																		{message.regenerations &&
																			message.regenerations.length > 1 && (
																				<>
																					<div className="flex items-center gap-1">
																						<Tooltip content={t("aiChat.previousVariant")}>
																						<button
																							type="button"
																							onClick={() =>
																								handleNavigateVariant(index, "prev")
																							}
																							disabled={activeIdx === 0}
																							className={`transition-colors ${activeIdx === 0 ? "opacity-30 cursor-not-allowed" : "hover:text-gray-600"}`}
																						>
																							<ChevronLeft className="w-4 h-4" />
																						</button>
																						</Tooltip>
																						<span className="text-xs text-gray-500 min-w-[28px] text-center tabular-nums">
																							{activeIdx + 1}/{message.regenerations.length}
																						</span>
																						<Tooltip content={t("aiChat.nextVariant")}>
																						<button
																							type="button"
																							onClick={() =>
																								handleNavigateVariant(index, "next")
																							}
																							disabled={
																								activeIdx ===
																								message.regenerations.length - 1
																							}
																							className={`transition-colors ${activeIdx === message.regenerations.length - 1 ? "opacity-30 cursor-not-allowed" : "hover:text-gray-600"}`}
																						>
																							<ChevronRight className="w-4 h-4" />
																						</button>
																						</Tooltip>
																					</div>
																					<div className="w-px h-4 bg-gray-200" />
																				</>
																			)}

																		{/* Timestamp */}
																		<span
																			className="text-xs text-gray-400"
																			title={message.timestamp.toLocaleString()}
																		>
																			{formatTimestamp(message.timestamp)}
																		</span>

																		<div className="w-px h-4 bg-gray-200" />

																		{/* Thumbs Up/Down Buttons */}
																		<Tooltip content={t("aiChat.goodResponse")}>
																		<button
																			type="button"
																			onClick={() =>
																				handleFeedback(message.id, "thumbs_up")
																			}
																			disabled={
																				feedbackPending ||
																				persistedMessageId === null
																			}
																			className={`transition-colors ${feedbackPending || persistedMessageId === null ? "opacity-50 cursor-not-allowed" : ""} ${
																				feedbacks.get(
																					parseInt(message.id, 10),
																				) === "thumbs_up"
																					? "text-green-500"
																					: "hover:text-gray-600"
																			}`}
																		>
																			<ThumbsUp className="w-4 h-4" />
																		</button>
																		</Tooltip>
																		<Tooltip content={t("aiChat.badResponse")}>
																		<button
																			type="button"
																			onClick={() =>
																				handleFeedback(
																					message.id,
																					"thumbs_down",
																				)
																			}
																			disabled={
																				feedbackPending ||
																				persistedMessageId === null
																			}
																			className={`transition-colors ${feedbackPending || persistedMessageId === null ? "opacity-50 cursor-not-allowed" : ""} ${
																				feedbacks.get(
																					parseInt(message.id, 10),
																				) === "thumbs_down"
																					? "text-red-500"
																					: "hover:text-gray-600"
																			}`}
																		>
																			<ThumbsDown className="w-4 h-4" />
																		</button>
																		</Tooltip>

																		<div className="w-px h-4 bg-gray-200" />

																		<Tooltip content={t("aiChat.copy")}>
																		<button
																			type="button"
																			onClick={() =>
																				handleCopy(message.content)
																			}
																			className="hover:text-gray-600 transition-colors"
																		>
																			<svg
																				aria-hidden="true"
																				width="16"
																				height="16"
																				viewBox="0 0 24 24"
																				fill="none"
																				stroke="currentColor"
																				strokeWidth="2"
																				strokeLinecap="round"
																				strokeLinejoin="round"
																			>
																				<rect
																					x="9"
																					y="9"
																					width="13"
																					height="13"
																					rx="2"
																					ry="2"
																				></rect>
																				<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
																			</svg>
																		</button>
																		</Tooltip>
																		<Tooltip content={t("aiChat.regenerate")}>
																		<button
																			type="button"
																			onClick={() =>
																				handleRegenerate(index)
																			}
																			disabled={isGenerating}
																			className={`hover:text-gray-600 transition-colors ${isGenerating ? "opacity-50 cursor-not-allowed" : ""}`}
																		>
																			<svg
																				aria-hidden="true"
																				width="16"
																				height="16"
																				viewBox="0 0 24 24"
																				fill="none"
																				stroke="currentColor"
																				strokeWidth="2"
																				strokeLinecap="round"
																				strokeLinejoin="round"
																			>
																				<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
																				<path d="M3 3v5h5"></path>
																				<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path>
																				<path d="M16 16h5v5"></path>
																			</svg>
																		</button>
																		</Tooltip>
																		{isLatestAssistantMessage && (
																			<>
																				<Tooltip content={t("aiChat.branchConversation")}>
																					<button
																						type="button"
																						onClick={handleBranchConversation}
																						disabled={!currentConversationId || isGenerating}
																						className={`hover:text-gray-600 transition-colors ${!currentConversationId || isGenerating ? "opacity-50 cursor-not-allowed" : ""}`}
																					>
																			<BranchForkIcon className="w-4 h-4" />
																					</button>
																				</Tooltip>
																				<div className="w-px h-4 bg-gray-200" />
																			</>
																		)}
																		<Tooltip content={t("aiChat.deleteMessageAndContinue")}>
																		<button
																			type="button"
																			onClick={() => handleDeleteMessage(index)}
																			disabled={isGenerating}
																			className={`hover:text-red-500 transition-colors ${isGenerating ? "opacity-50 cursor-not-allowed" : ""}`}
																		>
																			<Trash2 className="w-4 h-4" />
																		</button>
																		</Tooltip>
																	</>
																);
															})()}
														</div>
													)}

												{/* Timestamp & Actions for User Messages */}
												{message.role === "user" && (
													<div className="flex items-center gap-2 mt-1.5 mr-1 text-gray-400 justify-end">
														{/* Timestamp */}
														<span
															className="text-xs text-gray-400"
															title={message.timestamp.toLocaleString()}
														>
															{formatTimestamp(message.timestamp)}
														</span>

														<div className="w-px h-4 bg-gray-200" />

																		<Tooltip content={t("aiChat.copy")}>
																<button
																	type="button"
																	onClick={() => handleCopy(message.content)}
																	className="hover:text-gray-600 transition-colors"
																>
																	<svg
																		aria-hidden="true"
																		width="16"
																		height="16"
																		viewBox="0 0 24 24"
																		fill="none"
																		stroke="currentColor"
																		strokeWidth="2"
																		strokeLinecap="round"
																		strokeLinejoin="round"
																	>
																		<rect
																			x="9"
																			y="9"
																			width="13"
																			height="13"
																			rx="2"
																			ry="2"
																		></rect>
																		<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
																	</svg>
																</button>
																</Tooltip>

															<Tooltip content={t("aiChat.deleteMessageAndContinue")}>
															<button
																type="button"
																onClick={() => handleDeleteMessage(index)}
																disabled={isGenerating}
																className={`hover:text-red-500 transition-colors ${isGenerating ? "opacity-50 cursor-not-allowed" : ""}`}
															>
																<Trash2 className="w-4 h-4" />
															</button>
															</Tooltip>
													</div>
												)}
																</div>
															</div>
															{branchSeparatorAfterIndex === index &&
																currentConversationMeta?.parent_conversation_id && (
																	<div className="flex items-center gap-3 py-1">
																		<div className="h-px flex-1 bg-gray-200" />
																		<div className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-violet-100 bg-white px-2.5 py-1 text-xs text-gray-500 shadow-sm">
																			<BranchForkIcon className="h-3.5 w-3.5 flex-shrink-0 text-violet-500" />
																			<span>{t("aiChat.branchedFrom")}</span>
																			<Link
																				to={`/dashboard/${currentConversationMeta.parent_conversation_id}`}
																				className="max-w-[260px] truncate text-primary-600 hover:text-primary-700 underline underline-offset-2"
																			>
																				{currentConversationMeta.parent_conversation_title ||
																					t("aiChat.originalConversation")}
																			</Link>
																		</div>
																		<div className="h-px flex-1 bg-gray-200" />
																	</div>
																)}
											</Fragment>
														);
								});
							})()}

							{/* Live Input Preview Bubble - shows text input or voice transcript in real-time */}
							{(realtimePartialText || input.trim()) && (
								<div className="flex gap-4 flex-row-reverse items-start animate-in fade-in slide-in-from-bottom-2 duration-200 mb-6">
									{/* Avatar */}
									<div className="flex-shrink-0">
										<div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center shadow-md ring-2 ring-white">
											<User className="w-5 h-5 text-white" />
										</div>
									</div>

									{/* Message Content */}
									<div className="flex-1 min-w-0 max-w-[80%] flex flex-col items-end">
										{/* Message Bubble - slightly transparent for preview effect */}
										<div className="relative px-5 py-3.5 text-[15px] leading-7 shadow-sm bg-gradient-to-br from-primary-400 to-primary-500 text-white rounded-[20px] rounded-tr-sm selection:bg-white/30 opacity-80 max-h-[120px] overflow-y-auto scrollbar-hide">
											<div className="whitespace-pre-wrap break-words flex items-center gap-2">
												<span>{realtimePartialText || input}</span>
												{/* Show typing indicator only for voice input */}
												{realtimePartialText && (
													<span className="inline-flex gap-0.5">
														<span
															className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce"
															style={{ animationDelay: "0ms" }}
														/>
														<span
															className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce"
															style={{ animationDelay: "150ms" }}
														/>
														<span
															className="w-1.5 h-1.5 bg-white/70 rounded-full animate-bounce"
															style={{ animationDelay: "300ms" }}
														/>
													</span>
												)}
											</div>
										</div>
									</div>
								</div>
							)}

							<div ref={messagesEndRef} />
						</div>
					</div>
				</div>

				{/* Input Area - Floating Island - Fixed to viewport bottom */}
				<div
				className={`fixed bottom-[max(1.5rem,calc(env(safe-area-inset-bottom,0px)+0.5rem))] left-0 right-0 px-4 z-30 pointer-events-none transition-[left] duration-300 ease-in-out ${showHistory ? "lg:left-[18rem]" : "lg:left-[3.75rem]"}`}
			>
					<div className="max-w-4xl mx-auto pointer-events-auto relative">
						{/* Jump to bottom button */}
						<div
							className={`absolute -top-16 left-1/2 -translate-x-1/2 transition-all duration-300 pointer-events-auto z-40 ${
								hasScrolledAway ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none"
							}`}
						>
							<Tooltip content={t("aiChat.jumpToBottom")}>
							<button
								type="button"
								onClick={() => {
									userScrolledAwayRef.current = false;
									setHasScrolledAway(false);
									scrollToBottom();
								}}
								className="w-10 h-10 bg-white/95 backdrop-blur shadow-[0_4px_16px_rgba(0,0,0,0.12)] border border-gray-100/50 rounded-full flex items-center justify-center text-gray-500 hover:text-gray-900 hover:shadow-md transition-all duration-200"
								aria-label={t("aiChat.jumpToBottom")}
							>
								<ChevronDown className="w-5 h-5" />
								{isGenerating && (
									<span className="absolute -top-0.5 -right-0.5 flex h-2.5 w-2.5">
										<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-75"></span>
										<span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-primary-500 border-2 border-white"></span>
									</span>
								)}
							</button>
							</Tooltip>
						</div>

						<form
							ref={formRef}
							id="chat-form"
							onSubmit={handleSubmit}
							className="relative group"
						>
							<div
								className={`
                relative flex flex-col
                bg-white/80 backdrop-blur-xl
                rounded-[28px] shadow-[0_8px_32px_rgba(0,0,0,0.12)]
                border transition-all duration-300
                ${
									voiceSessionActive
										? "border-primary-300 shadow-[0_0_0_4px_rgba(102,126,234,0.15)] bg-white/90"
										: "border-gray-200/50 hover:border-gray-300/80 hover:shadow-[0_8px_40px_rgba(0,0,0,0.15)]"
								}
                min-h-[56px] py-1.5
              `}
							>
								{/* Inline Attachments Preview */}
								{(imageAttachments.length > 0 ||
									fileAttachments.length > 0) && (
									<div className="flex flex-wrap gap-2 px-4 pt-2.5 pb-1 animate-in fade-in slide-in-from-bottom-1 duration-200">
										{imageAttachments.map((attachment) => (
											<div
												key={attachment.id}
												className="relative group/thumb flex-shrink-0"
											>
												<div className="w-16 h-16 sm:w-[72px] sm:h-[72px] rounded-xl overflow-hidden ring-1 ring-gray-200/60 shadow-sm bg-gray-50">
													<img
														src={attachment.preview}
														alt={t("aiChat.attachment")}
														className="w-full h-full object-cover"
													/>
												</div>
												<button
													type="button"
													onClick={() => handleImageRemove(attachment.id)}
													className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-800/90 hover:bg-red-500 text-white rounded-full flex items-center justify-center opacity-100 sm:opacity-0 sm:group-hover/thumb:opacity-100 transition-all shadow-sm"
													aria-label={t("aiChat.removeAttachment")}
												>
													<X className="w-3 h-3" />
												</button>
											</div>
										))}
										{fileAttachments.map((attachment) => (
											<div
												key={attachment.id}
												className="relative group/thumb flex-shrink-0"
											>
												<div className="h-16 sm:h-[72px] flex items-center gap-2 px-3 rounded-xl bg-gray-50/80 ring-1 ring-gray-200/60">
													<FileSpreadsheet className="w-5 h-5 text-emerald-600 flex-shrink-0" />
													<div className="max-w-[100px] sm:max-w-[140px]">
														<div className="text-xs font-medium text-gray-800 truncate">
															{attachment.name}
														</div>
														<div className="text-[10px] text-gray-400 uppercase">
															{attachment.type}
														</div>
													</div>
												</div>
												<button
													type="button"
													onClick={() => handleFileRemove(attachment.id)}
													className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-800/90 hover:bg-red-500 text-white rounded-full flex items-center justify-center opacity-100 sm:opacity-0 sm:group-hover/thumb:opacity-100 transition-all shadow-sm"
													aria-label={t("aiChat.removeAttachment")}
												>
													<X className="w-3 h-3" />
												</button>
											</div>
										))}
									</div>
								)}

								<div className="relative flex items-center min-h-[52px] pl-4 pr-[104px] sm:pr-[120px]">
									<textarea
										ref={textareaRef}
										value={input}
										onChange={(e) => setInput(e.target.value)}
										onKeyDown={handleKeyDown}
										placeholder={
											voiceSessionActive
												? t("aiChat.listening")
												: t("aiChat.inputPlaceholder")
										}
										className={`
                    w-full bg-transparent border-none focus:outline-none resize-none 
                    text-gray-900 placeholder-gray-400 transition-all 
                    text-[15px] leading-relaxed py-2.5 scrollbar-hide
                    ${realtimeIsRecording || voiceSessionActive ? "opacity-0" : "opacity-100"}
                  `}
										rows={1}
										style={{ maxHeight: "150px" }}
										disabled={isGenerating}
										aria-label={t("aiChat.messageInput")}
									/>

									{/* Hidden file input */}
									<input
										ref={fileInputRef}
										type="file"
										accept="image/*,.csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
										multiple
										onChange={handleFileSelect}
										className="hidden"
									/>

									{/* Voice Visualizer Overlay with Realtime Transcript */}
									{(realtimeIsRecording || realtimeIsConnecting) && (
										<div className="absolute left-4 right-[140px] top-0 bottom-0 flex items-center pointer-events-none">
											{realtimePartialText ? (
												// Show realtime transcript when available
												<div className="w-full flex items-center gap-2 text-gray-700 text-[15px] leading-relaxed overflow-hidden">
													<span className="truncate">
														{realtimePartialText}
													</span>
													<span className="flex-shrink-0 inline-flex gap-0.5">
														<span
															className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce"
															style={{ animationDelay: "0ms" }}
														/>
														<span
															className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce"
															style={{ animationDelay: "150ms" }}
														/>
														<span
															className="w-1.5 h-1.5 bg-primary-500 rounded-full animate-bounce"
															style={{ animationDelay: "300ms" }}
														/>
													</span>
												</div>
											) : (
												// Show audio visualizer when no transcript yet
												<AudioVisualizer
													stream={realtimeMediaStream}
													isActive={realtimeIsRecording}
													className="w-full h-12 opacity-80"
												/>
											)}
										</div>
									)}

									{/* Voice Session Waiting State */}
									{voiceSessionActive && !realtimeIsRecording && isLoading && (
										<div className="absolute left-4 right-[140px] top-0 bottom-0 flex items-center justify-center pointer-events-none">
											<span className="flex items-center gap-2 text-sm text-primary-600 font-medium animate-pulse">
												<div
													className="w-2 h-2 rounded-full bg-primary-500 animate-bounce"
													style={{ animationDelay: "0ms" }}
												/>
												<div
													className="w-2 h-2 rounded-full bg-primary-500 animate-bounce"
													style={{ animationDelay: "150ms" }}
												/>
												<div
													className="w-2 h-2 rounded-full bg-primary-500 animate-bounce"
													style={{ animationDelay: "300ms" }}
												/>
												{t("aiChat.thinking")}
											</span>
										</div>
									)}

									<div className="absolute right-1.5 bottom-1.5 flex items-center gap-1 sm:gap-1.5">
										{/* File Upload - hidden during voice recording */}
										{!realtimeIsRecording &&
											!realtimeIsConnecting &&
											!voiceSessionActive && (
												<button
													type="button"
													onClick={() => fileInputRef.current?.click()}
													disabled={isGenerating}
													className="p-2 sm:p-2.5 rounded-full transition-all text-gray-400 hover:text-gray-600 hover:bg-gray-100 active:scale-95 disabled:opacity-50"
													aria-label={t("aiChat.attachFile")}
												>
													<Paperclip className="w-4 h-4 sm:w-5 sm:h-5" />
												</button>
											)}

										{/* Voice Button */}
										<button
											type="button"
											onClick={toggleVoiceSession}
											disabled={isGenerating && !voiceSessionActive}
											aria-label={
												voiceSessionActive || realtimeIsRecording
													? t("aiChat.stopVoiceInput")
													: t("aiChat.voiceInput")
											}
											className={`
                      p-2 sm:p-2.5 rounded-full transition-all duration-300 active:scale-95
                      ${
												realtimeIsRecording
													? "bg-red-50 text-red-500 hover:bg-red-100"
													: realtimeIsConnecting
														? "bg-primary-50 text-primary-500"
														: voiceSessionActive
															? "bg-primary-500 text-white shadow-md"
															: "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
											}
                    `}
										>
											{realtimeIsConnecting ? (
												<Loader2 className="w-4 h-4 sm:w-5 sm:h-5 animate-spin" />
											) : realtimeIsRecording ? (
												<Square
													className="w-3.5 h-3.5 sm:w-4 sm:h-4"
													fill="currentColor"
												/>
											) : voiceSessionActive ? (
												<MicOff className="w-4 h-4 sm:w-5 sm:h-5" />
											) : (
												<Mic className="w-4 h-4 sm:w-5 sm:h-5" />
											)}
										</button>

										{/* Send / Stop Button */}
										{isGenerating ? (
											<Tooltip content={t("aiChat.stopGenerating")}>
											<button
												type="button"
												onClick={handleStopGeneration}
												className="p-2 sm:p-2.5 rounded-full transition-all duration-300 shadow-sm bg-gray-800 text-white hover:bg-gray-900 shadow-md active:scale-95"
												aria-label={t("aiChat.stopGenerating")}
											>
												<Square
													className="w-3.5 h-3.5 sm:w-4 sm:h-4"
													fill="currentColor"
												/>
											</button>
											</Tooltip>
										) : realtimeIsRecording ? (
											/* Force-send partial transcript during recording */
											<button
												type="button"
												onClick={() => voiceForceSend(realtimePartialText)}
												disabled={!realtimePartialText?.trim()}
												aria-label={t("aiChat.sendVoiceMessage")}
												className={`
                        p-2 sm:p-2.5 rounded-full transition-all duration-300 shadow-sm
                        ${
													!realtimePartialText?.trim()
														? "bg-gray-100 text-gray-300 cursor-not-allowed"
														: "bg-primary-600 text-white hover:bg-primary-700 shadow-md active:scale-95"
												}
                      `}
											>
												<Send className="w-4 h-4 sm:w-5 sm:h-5" />
											</button>
										) : (
											<button
												type="submit"
												disabled={
													!input.trim() &&
													imageAttachments.length === 0 &&
													fileAttachments.length === 0
												}
												aria-label={t("aiChat.sendMessage")}
												className={`
                          p-2 sm:p-2.5 rounded-full transition-all duration-300 shadow-sm
                          ${
														!input.trim() &&
														imageAttachments.length === 0 &&
														fileAttachments.length === 0
															? "bg-gray-100 text-gray-300 cursor-not-allowed"
															: "bg-primary-600 text-white hover:bg-primary-700 shadow-md active:scale-95"
													}
                      `}
											>
												<Send className="w-4 h-4 sm:w-5 sm:h-5" />
											</button>
										)}
									</div>
								</div>
							</div>
						</form>

						<div className="mt-2 text-center text-xs text-gray-400/80 font-medium px-4 leading-relaxed">
							{t("aiChat.disclaimer")}
						</div>
					</div>
				</div>
			</div>

			{/* Delete Confirmation Modal */}
			{deleteConfirmId && (
				<div
					className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4"
					role="dialog"
					aria-modal="true"
					aria-labelledby="delete-dialog-title"
					onKeyDown={(e) => e.key === "Escape" && cancelDelete()}
				>
					<div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all scale-100">
						<div className="flex items-start gap-4">
							<div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
								<Trash2 className="w-6 h-6 text-red-600" />
							</div>
							<div className="flex-1">
								<h3
									id="delete-dialog-title"
									className="text-lg font-semibold text-gray-900 mb-2"
								>
									{deleteConfirmId === "all-conversations"
										? t("aiChat.deleteAllHistoryTitle")
										: t("aiChat.deleteConversationTitle")}
								</h3>
								<p className="text-sm text-gray-600 mb-6">
									{deleteConfirmId === "all-conversations"
										? t("aiChat.deleteAllHistoryConfirm")
										: t("aiChat.deleteConversationConfirm")}
								</p>
								<div className="flex gap-3 justify-end">
									<button
										type="button"
										onClick={cancelDelete}
										className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
									>
										{t("common.cancel")}
									</button>
									<button
										type="button"
										onClick={confirmDelete}
										className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors shadow-sm"
									>
										{t("common.delete")}
									</button>
								</div>
							</div>
						</div>
					</div>
				</div>
			)}

			{/* Toast notification */}
			{toastMessage && (
				<div
					className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-in slide-in-from-top-2 duration-300 ${
						toastMessage.type === "error"
							? "bg-red-500 text-white"
							: toastMessage.type === "success"
								? "bg-green-500 text-white"
								: "bg-blue-500 text-white"
					}`}
					role={toastMessage.type === "error" ? "alert" : "status"}
					aria-live={toastMessage.type === "error" ? "assertive" : "polite"}
				>
					<span>{toastMessage.message}</span>
					<button
						type="button"
						onClick={() => setToastMessage(null)}
						className="ml-2 hover:opacity-80"
						aria-label={t("aiChat.closeNotification")}
					>
						×
					</button>
				</div>
			)}
		</section>
	);
}
