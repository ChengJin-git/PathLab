import { useCallback, useEffect, useMemo, useState } from "react";
import { useDebounce } from "../../lib/useDebounce";
import { useTranslation } from "react-i18next";
import { ModalShell } from "../ui/modal-shell";
import {
  ArrowRightLeft,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  Eye,
  Globe,
  Key,
  Lock,
  Search,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select } from "../ui/select";
import { cn } from "../../lib/utils";
import {
  batchGrantDatasetGrants,
  batchRevokeDatasetGrants,
  fetchDatasets,
  getUserDatasetGrants,
  grantDatasetGrant,
  listDatasetGrants,
  listUsersPaged,
  revokeDatasetGrant,
  updateDatasetVisibility,
} from "../../api";
import type { DatasetGrant } from "../../api/grants";
import type { UserListItem } from "../../api/users";
import type { DatasetSummary } from "../../api/wsi";
import type { ShowConfirmDialog } from "./ConfirmDialog";

type PermissionMode = "user" | "dataset";
type PermissionDataset = DatasetSummary & { dataset_id: string };

const PAGE_SIZE_OPTIONS = ["4", "6", "9", "18"];
const SEARCH_DEBOUNCE_MS = 300;
const PRIVATE_DATASET_FILTER = { is_public: false as const };

export interface PermissionCenterModalProps {
  showConfirmDialog: ShowConfirmDialog;
  closeConfirmDialog: () => void;
  onClose: () => void;
  initialMode?: PermissionMode;
  onModeChange?: (mode: PermissionMode) => void;
}

function getRoleBadgeColor(role: string) {
  switch (role) {
    case "admin":
      return "bg-red-100 text-red-800 border-red-200";
    case "pathologist":
      return "bg-primary-100 text-primary-800 border-primary-200";
    case "guest":
      return "bg-gray-100 text-gray-800 border-gray-200";
    default:
      return "bg-gray-100 text-gray-800 border-gray-200";
  }
}

function parsePositiveHours(value: string): number | undefined {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function getUserDisplayName(user?: Partial<UserListItem> | null) {
  return user?.nickname || user?.email || "-";
}

function PaginationFooter({
  page,
  pageSize,
  total,
  disabled,
  onPageChange,
  onPageSizeChange,
  t,
}: {
  page: number;
  pageSize: number;
  total: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);

  return (
    <div className="flex flex-col gap-3 border-t border-gray-200 pt-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <span>{t("settings.permissionCenterModal.itemsPerPage")}</span>
        <Select
          value={String(pageSize)}
          onChange={(value) => onPageSizeChange(Number(value))}
          options={PAGE_SIZE_OPTIONS.map((value) => ({ value, label: value }))}
          className="w-20"
          disabled={disabled}
        />
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <span className="text-sm text-gray-500">
          {t("settings.permissionCenterModal.pageInfo", {
            current: Math.min(page, totalPages),
            total: totalPages,
            count: total,
          })}
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={disabled || page <= 1}
            className="gap-1"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            {t("settings.permissionCenterModal.previous")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={disabled || page >= totalPages}
            className="gap-1"
          >
            {t("settings.permissionCenterModal.next")}
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function BulkSelectionBanner({
  allPageSelected,
  allMatchingSelected,
  pageCount,
  selectedCount,
  selectingAll,
  onSelectAllMatching,
  onClearSelection,
}: {
  allPageSelected: boolean;
  allMatchingSelected: boolean;
  pageCount: number;
  selectedCount: number;
  selectingAll?: boolean;
  onSelectAllMatching: () => void;
  onClearSelection: () => void;
}) {
  const { t } = useTranslation();

  if (allMatchingSelected && selectedCount > 0) {
    return (
      <div className="mb-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-gray-700">
        <span className="font-medium">
          {t("settings.permissionCenterModal.allMatchingItemsSelected", {
            count: selectedCount,
          })}
        </span>
        <button
          type="button"
          onClick={onClearSelection}
          className="ml-2 font-semibold text-blue-600 hover:text-blue-800 hover:underline"
        >
          {t("settings.permissionCenterModal.clearSelection")}
        </button>
      </div>
    );
  }

  if (allPageSelected && pageCount > 0) {
    return (
      <div className="mb-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-gray-700">
        <span className="font-medium">
          {t("settings.permissionCenterModal.allPageItemsSelected", {
            count: pageCount,
          })}
        </span>
        <button
          type="button"
          onClick={onSelectAllMatching}
          disabled={selectingAll}
          className="ml-2 font-semibold text-blue-600 hover:text-blue-800 hover:underline disabled:cursor-not-allowed disabled:opacity-60"
        >
          {selectingAll
            ? t("settings.permissionCenterModal.selectingAll")
            : t("settings.permissionCenterModal.selectAllMatchingItems")}
        </button>
      </div>
    );
  }

  return null;
}

export function PermissionCenterModal({
  showConfirmDialog,
  closeConfirmDialog,
  onClose,
  initialMode = "user",
  onModeChange,
}: PermissionCenterModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<PermissionMode>(initialMode);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expiresInHours, setExpiresInHours] = useState("");
  const [datasetSearchQuery, setDatasetSearchQuery] = useState("");

  const [datasetPage, setDatasetPage] = useState(1);
  const [datasetPageSize, setDatasetPageSize] = useState(9);
  const [grantDatasetPage, setGrantDatasetPage] = useState(1);
  const [grantDatasetPageSize, setGrantDatasetPageSize] = useState(4);
  const [datasetItems, setDatasetItems] = useState<DatasetSummary[]>([]);
  const [datasetTotal, setDatasetTotal] = useState(0);
  const [loadingDatasets, setLoadingDatasets] = useState(false);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [userSearchQuery, setUserSearchQuery] = useState("");

  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(9);
  const [userItems, setUserItems] = useState<UserListItem[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [grantUserSearchQuery, setGrantUserSearchQuery] = useState("");

  const [grantUserPage, setGrantUserPage] = useState(1);
  const [grantUserPageSize, setGrantUserPageSize] = useState(9);
  const [grantUserItems, setGrantUserItems] = useState<UserListItem[]>([]);
  const [grantUserTotal, setGrantUserTotal] = useState(0);
  const [loadingGrantUsers, setLoadingGrantUsers] = useState(false);
  const [userPermissions, setUserPermissions] = useState<DatasetGrant[]>([]);
  const [datasetPermissions, setDatasetGrants] = useState<DatasetGrant[]>([]);
  const [loadingUserPermissions, setLoadingUserPermissions] = useState(false);
  const [loadingDatasetGrants, setLoadingDatasetGrants] = useState(false);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [selectedGrantUserIds, setSelectedGrantUserIds] = useState<string[]>(
    [],
  );
  const [selectingAllDatasets, setSelectingAllDatasets] = useState(false);
  const [selectingAllUsers, setSelectingAllUsers] = useState(false);
  const [allMatchingDatasetsSelected, setAllMatchingDatasetsSelected] =
    useState(false);
  const [allMatchingUsersSelected, setAllMatchingUsersSelected] =
    useState(false);
  const [allMatchingDatasetCount, setAllMatchingDatasetCount] = useState(0);
  const [allMatchingUserCount, setAllMatchingUserCount] = useState(0);
  const [selectedVisibilityDatasetIds, setSelectedVisibilityDatasetIds] =
    useState<string[]>([]);
  const [visibilityTarget, setVisibilityTarget] = useState<
    "public" | "private"
  >("private");

  const pagedDatasets = useMemo(
    () =>
      datasetItems.filter((item): item is PermissionDataset =>
        Boolean(item.dataset_id),
      ),
    [datasetItems],
  );
  const selectedDataset = useMemo(
    () =>
      pagedDatasets.find(
        (dataset) => dataset.dataset_id === selectedDatasetId,
      ) ?? null,
    [pagedDatasets, selectedDatasetId],
  );
  const selectedUser = useMemo(
    () => userItems.find((user) => user.id === selectedUserId) ?? null,
    [selectedUserId, userItems],
  );
  const validUserPermissions = useMemo(
    () =>
      userPermissions.filter(
        (permission) => permission.is_valid && permission.can_read,
      ),
    [userPermissions],
  );
  const validUserDatasetIds = useMemo(
    () =>
      new Set(validUserPermissions.map((permission) => permission.dataset_id)),
    [validUserPermissions],
  );
  const sortedUserPermissions = useMemo(
    () =>
      [...validUserPermissions].sort((a, b) =>
        a.is_valid !== b.is_valid
          ? a.is_valid
            ? -1
            : 1
          : (a.dataset_name || a.dataset_id).localeCompare(
              b.dataset_name || b.dataset_id,
            ),
      ),
    [validUserPermissions],
  );
  const selectableDatasetIdsOnPage = useMemo(
    () =>
      pagedDatasets
        .filter(
          (dataset) =>
            !dataset.is_public &&
            !validUserDatasetIds.has(dataset.dataset_id) &&
            dataset.user_id !== selectedUser?.id,
        )
        .map((dataset) => dataset.dataset_id),
    [pagedDatasets, validUserDatasetIds, selectedUser],
  );
  const selectableDatasetIdSetOnPage = useMemo(
    () => new Set(selectableDatasetIdsOnPage),
    [selectableDatasetIdsOnPage],
  );
  const pagedDatasetIdSet = useMemo(
    () => new Set(pagedDatasets.map((dataset) => dataset.dataset_id)),
    [pagedDatasets],
  );
  const selectedGrantableDatasetIds = useMemo(
    () =>
      selectedDatasetIds.filter(
        (datasetId) =>
          !pagedDatasetIdSet.has(datasetId) ||
          selectableDatasetIdSetOnPage.has(datasetId),
      ),
    [selectedDatasetIds, pagedDatasetIdSet, selectableDatasetIdSetOnPage],
  );
  const allVisibleDatasetsSelected = useMemo(
    () =>
      selectableDatasetIdsOnPage.length > 0 &&
      selectableDatasetIdsOnPage.every((datasetId) =>
        selectedDatasetIds.includes(datasetId),
      ),
    [selectableDatasetIdsOnPage, selectedDatasetIds],
  );
  const validDatasetGrants = useMemo(
    () =>
      datasetPermissions.filter(
        (permission) =>
          permission.is_valid &&
          permission.can_read &&
          permission.user_role !== "admin",
      ),
    [datasetPermissions],
  );
  const validDatasetGrantUserIds = useMemo(
    () => new Set(validDatasetGrants.map((permission) => permission.user_id)),
    [validDatasetGrants],
  );
  const sortedDatasetGrants = useMemo(
    () =>
      [...validDatasetGrants].sort((a, b) =>
        a.is_valid !== b.is_valid
          ? a.is_valid
            ? -1
            : 1
          : (a.user_nickname || a.user_email || a.user_id).localeCompare(
              b.user_nickname || b.user_email || b.user_id,
            ),
      ),
    [validDatasetGrants],
  );
  const selectedDatasetIsPublic = Boolean(selectedDataset?.is_public);
  const selectableGrantUsers = useMemo(
    () =>
      grantUserItems.filter(
        (user) =>
          !validDatasetGrantUserIds.has(user.id) &&
          user.id !== selectedDataset?.user_id,
      ),
    [grantUserItems, validDatasetGrantUserIds, selectedDataset],
  );
  const allVisibleUsersSelected = useMemo(
    () =>
      selectableGrantUsers.length > 0 &&
      selectableGrantUsers.every((user) =>
        selectedGrantUserIds.includes(user.id),
      ),
    [selectableGrantUsers, selectedGrantUserIds],
  );

  const debouncedUserSearchQuery = useDebounce(userSearchQuery, SEARCH_DEBOUNCE_MS);
  const debouncedDatasetSearchQuery = useDebounce(datasetSearchQuery, SEARCH_DEBOUNCE_MS);
  const debouncedGrantUserSearchQuery = useDebounce(grantUserSearchQuery, SEARCH_DEBOUNCE_MS);

  const fetchAllSelectableDatasetIds = useCallback(async () => {
    const response = await fetchDatasets(undefined, {
      ...PRIVATE_DATASET_FILTER,
      search: debouncedDatasetSearchQuery.trim() || undefined,
      page_size: 0,
    });
    return response.items
      .filter((item): item is PermissionDataset => Boolean(item.dataset_id))
      .filter(
        (item) =>
          !validUserDatasetIds.has(item.dataset_id) &&
          item.user_id !== selectedUser?.id,
      )
      .map((item) => item.dataset_id);
  }, [debouncedDatasetSearchQuery, validUserDatasetIds, selectedUser]);

  const fetchAllSelectableGrantUserIds = useCallback(async () => {
    const pageSize = 100;
    let page = 1;
    let total = 0;
    const ids: string[] = [];

    do {
      const response = await listUsersPaged({
        page,
        page_size: pageSize,
        search: debouncedGrantUserSearchQuery.trim() || undefined,
        exclude_admin: true,
      });
      total = response.total;
      response.items.forEach((user) => {
        if (
          !validDatasetGrantUserIds.has(user.id) &&
          user.id !== selectedDataset?.user_id
        )
          ids.push(user.id);
      });
      page += 1;
    } while ((page - 1) * pageSize < total);

    return Array.from(new Set(ids));
  }, [
    debouncedGrantUserSearchQuery,
    validDatasetGrantUserIds,
    selectedDataset,
  ]);

  const loadDatasets = useCallback(async () => {
    setLoadingDatasets(true);
    try {
      const page = mode === "dataset" ? datasetPage : grantDatasetPage;
      const pageSize =
        mode === "dataset" ? datasetPageSize : grantDatasetPageSize;
      const baseQuery = mode === "dataset" ? {} : PRIVATE_DATASET_FILTER;
      const response = await fetchDatasets(undefined, {
        ...baseQuery,
        page,
        page_size: pageSize,
        search: debouncedDatasetSearchQuery.trim() || undefined,
      });
      setDatasetItems(response.items);
      setDatasetTotal(response.total);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToLoadDatasets"),
      );
    } finally {
      setLoadingDatasets(false);
    }
  }, [
    mode,
    datasetPage,
    datasetPageSize,
    grantDatasetPage,
    grantDatasetPageSize,
    debouncedDatasetSearchQuery,
    t,
  ]);

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const response = await listUsersPaged({
        page: userPage,
        page_size: userPageSize,
        search: debouncedUserSearchQuery.trim() || undefined,
        exclude_admin: true,
      });
      setUserItems(response.items);
      setUserTotal(response.total);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToLoadUsers"),
      );
    } finally {
      setLoadingUsers(false);
    }
  }, [debouncedUserSearchQuery, t, userPage, userPageSize]);

  const loadGrantUsers = useCallback(async () => {
    setLoadingGrantUsers(true);
    try {
      const response = await listUsersPaged({
        page: grantUserPage,
        page_size: grantUserPageSize,
        search: debouncedGrantUserSearchQuery.trim() || undefined,
        exclude_admin: true,
      });
      setGrantUserItems(response.items);
      setGrantUserTotal(response.total);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToLoadUsers"),
      );
    } finally {
      setLoadingGrantUsers(false);
    }
  }, [debouncedGrantUserSearchQuery, grantUserPage, grantUserPageSize, t]);

  const loadUserPermissions = useCallback(
    async (userId: string) => {
      if (!userId) {
        setUserPermissions([]);
        return;
      }
      setLoadingUserPermissions(true);
      try {
        const response = await getUserDatasetGrants(userId);
        setUserPermissions(response.grants);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t("settings.permissionCenterModal.failedToLoadUserPermissions"),
        );
      } finally {
        setLoadingUserPermissions(false);
      }
    },
    [t],
  );

  const loadDatasetGrants = useCallback(
    async (datasetId: string) => {
      if (!datasetId) {
        setDatasetGrants([]);
        return;
      }
      setLoadingDatasetGrants(true);
      try {
        const response = await listDatasetGrants(datasetId);
        setDatasetGrants(response.grants);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : t("settings.permissionCenterModal.failedToLoadDatasetGrants"),
        );
      } finally {
        setLoadingDatasetGrants(false);
      }
    },
    [t],
  );

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);
  useEffect(() => {
    if (mode === "user") void loadUsers();
  }, [loadUsers, mode]);
  useEffect(() => {
    if (mode === "dataset") void loadGrantUsers();
  }, [loadGrantUsers, mode]);
  useEffect(() => {
    if (mode !== "user") return;
    if (userItems.length === 0) {
      setSelectedUserId("");
      setUserPermissions([]);
      return;
    }
    if (
      !selectedUserId ||
      !userItems.some((user) => user.id === selectedUserId)
    )
      setSelectedUserId(userItems[0].id);
  }, [mode, selectedUserId, userItems]);
  useEffect(() => {
    if (mode === "user" && selectedUserId)
      void loadUserPermissions(selectedUserId);
  }, [loadUserPermissions, mode, selectedUserId]);
  useEffect(() => {
    if (mode !== "dataset") return;
    if (pagedDatasets.length === 0) {
      setSelectedDatasetId("");
      setDatasetGrants([]);
      return;
    }
    if (
      !pagedDatasets.some((dataset) => dataset.dataset_id === selectedDatasetId)
    )
      setSelectedDatasetId(pagedDatasets[0].dataset_id);
  }, [mode, pagedDatasets, selectedDatasetId]);
  useEffect(() => {
    if (mode === "dataset" && selectedDatasetId)
      void loadDatasetGrants(selectedDatasetId);
  }, [loadDatasetGrants, mode, selectedDatasetId]);
  useEffect(() => {
    if (mode !== "dataset" || !selectedDatasetIsPublic) return;
    setSelectedGrantUserIds([]);
    setAllMatchingUsersSelected(false);
    setAllMatchingUserCount(0);
    setExpiresInHours("");
  }, [mode, selectedDatasetIsPublic]);
  useEffect(() => {
    if (mode !== "user") return;
    const hasInvalidSelectionOnPage = selectedDatasetIds.some(
      (datasetId) =>
        pagedDatasetIdSet.has(datasetId) &&
        !selectableDatasetIdSetOnPage.has(datasetId),
    );
    if (!hasInvalidSelectionOnPage) return;
    setSelectedDatasetIds((prev) =>
      prev.filter(
        (datasetId) =>
          !pagedDatasetIdSet.has(datasetId) ||
          selectableDatasetIdSetOnPage.has(datasetId),
      ),
    );
    setAllMatchingDatasetsSelected(false);
    setAllMatchingDatasetCount(0);
  }, [
    mode,
    selectedDatasetIds,
    pagedDatasetIdSet,
    selectableDatasetIdSetOnPage,
  ]);
  const handleModeChange = (nextMode: PermissionMode) => {
    setMode(nextMode);
    onModeChange?.(nextMode);
    setError(null);
    setExpiresInHours("");
    setSelectedDatasetIds([]);
    setSelectedGrantUserIds([]);
    setSelectedVisibilityDatasetIds([]);
    setAllMatchingDatasetsSelected(false);
    setAllMatchingUsersSelected(false);
    setAllMatchingDatasetCount(0);
    setAllMatchingUserCount(0);
  };
  const handleToggleAllDatasets = (checked: boolean) => {
    if (checked) {
      setSelectedDatasetIds((prev) =>
        Array.from(new Set([...prev, ...selectableDatasetIdsOnPage])),
      );
      setAllMatchingDatasetsSelected(false);
      setAllMatchingDatasetCount(0);
      return;
    }
    const visibleIdSet = new Set(selectableDatasetIdsOnPage);
    setSelectedDatasetIds((prev) =>
      prev.filter((datasetId) => !visibleIdSet.has(datasetId)),
    );
    setAllMatchingDatasetsSelected(false);
    setAllMatchingDatasetCount(0);
  };
  const handleToggleDataset = (datasetId: string, checked: boolean) => {
    if (checked && !selectableDatasetIdSetOnPage.has(datasetId)) return;
    setSelectedDatasetIds((prev) =>
      checked
        ? Array.from(new Set([...prev, datasetId]))
        : prev.filter((id) => id !== datasetId),
    );
    setAllMatchingDatasetsSelected(false);
    setAllMatchingDatasetCount(0);
  };
  const handleToggleAllUsers = (checked: boolean) => {
    if (checked) {
      setSelectedGrantUserIds((prev) =>
        Array.from(
          new Set([...prev, ...selectableGrantUsers.map((user) => user.id)]),
        ),
      );
      setAllMatchingUsersSelected(false);
      setAllMatchingUserCount(0);
      return;
    }
    const visibleIds = new Set(selectableGrantUsers.map((user) => user.id));
    setSelectedGrantUserIds((prev) =>
      prev.filter((userId) => !visibleIds.has(userId)),
    );
    setAllMatchingUsersSelected(false);
    setAllMatchingUserCount(0);
  };
  const handleToggleGrantUser = (userId: string, checked: boolean) => {
    setSelectedGrantUserIds((prev) =>
      checked
        ? Array.from(new Set([...prev, userId]))
        : prev.filter((id) => id !== userId),
    );
    setAllMatchingUsersSelected(false);
    setAllMatchingUserCount(0);
  };

  const handleSelectAllMatchingDatasets = async () => {
    try {
      setSelectingAllDatasets(true);
      setError(null);
      const ids = await fetchAllSelectableDatasetIds();
      setSelectedDatasetIds(ids);
      setAllMatchingDatasetsSelected(true);
      setAllMatchingDatasetCount(ids.length);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToSelectAllDatasets"),
      );
    } finally {
      setSelectingAllDatasets(false);
    }
  };

  const handleClearDatasetSelection = () => {
    setSelectedDatasetIds([]);
    setAllMatchingDatasetsSelected(false);
    setAllMatchingDatasetCount(0);
  };

  const handleSelectAllMatchingUsers = async () => {
    try {
      setSelectingAllUsers(true);
      setError(null);
      const ids = await fetchAllSelectableGrantUserIds();
      setSelectedGrantUserIds(ids);
      setAllMatchingUsersSelected(true);
      setAllMatchingUserCount(ids.length);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToSelectAllUsers"),
      );
    } finally {
      setSelectingAllUsers(false);
    }
  };

  const handleClearUserSelection = () => {
    setSelectedGrantUserIds([]);
    setAllMatchingUsersSelected(false);
    setAllMatchingUserCount(0);
  };

  const handleGrantToUser = async () => {
    if (!selectedUser || selectedGrantableDatasetIds.length === 0) return;
    try {
      setSubmitting(true);
      setError(null);
      const hours = parsePositiveHours(expiresInHours);
      const results = await Promise.allSettled(
        selectedGrantableDatasetIds.map((datasetId) =>
          grantDatasetGrant(datasetId, selectedUser.id, hours),
        ),
      );
      await loadUserPermissions(selectedUser.id);
      setSelectedDatasetIds([]);
      setAllMatchingDatasetsSelected(false);
      setAllMatchingDatasetCount(0);
      setExpiresInHours("");
      const failedCount = results.filter(
        (result) => result.status === "rejected",
      ).length;
      if (failedCount > 0)
        setError(
          t("settings.permissionCenterModal.partialGrantWarning", {
            failed: failedCount,
          }),
        );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToGrantUserPermissions"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevokeFromUser = (permission: DatasetGrant) => {
    if (!selectedUser) return;
    showConfirmDialog({
      title: t("settings.permissionCenterModal.revokePermission"),
      message: t("settings.permissionCenterModal.revokeUserPermissionConfirm", {
        datasetName: permission.dataset_name || permission.dataset_id,
        userName: getUserDisplayName(selectedUser),
      }),
      confirmText: t("settings.usersTab.revoke"),
      confirmVariant: "warning",
      onConfirm: async () => {
        closeConfirmDialog();
        try {
          setSubmitting(true);
          setError(null);
          await revokeDatasetGrant(permission.dataset_id, selectedUser.id);
          await loadUserPermissions(selectedUser.id);
        } catch (err) {
          setError(
            err instanceof Error
              ? err.message
              : t(
                  "settings.permissionCenterModal.failedToRevokeUserPermission",
                ),
          );
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const handleRevokeAllFromUser = () => {
    if (!selectedUser || validUserPermissions.length === 0) return;
    showConfirmDialog({
      title: t("settings.permissionCenterModal.revokeAllPermissions"),
      message: t(
        "settings.permissionCenterModal.revokeAllUserPermissionsConfirm",
        {
          userName: getUserDisplayName(selectedUser),
          count: validUserPermissions.length,
        },
      ),
      confirmText: t("settings.permissionCenterModal.revokeAll"),
      confirmVariant: "danger",
      onConfirm: async () => {
        closeConfirmDialog();
        try {
          setSubmitting(true);
          setError(null);
          const results = await Promise.allSettled(
            validUserPermissions.map((permission) =>
              revokeDatasetGrant(permission.dataset_id, selectedUser.id),
            ),
          );
          await loadUserPermissions(selectedUser.id);
          const failedCount = results.filter(
            (result) => result.status === "rejected",
          ).length;
          if (failedCount > 0)
            setError(
              t("settings.permissionCenterModal.partialRevokeWarning", {
                failed: failedCount,
              }),
            );
        } catch (err) {
          setError(
            err instanceof Error
              ? err.message
              : t(
                  "settings.permissionCenterModal.failedToRevokeUserPermissions",
                ),
          );
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const handleGrantToDataset = async () => {
    if (
      !selectedDatasetId ||
      selectedGrantUserIds.length === 0 ||
      selectedDatasetIsPublic
    )
      return;
    try {
      setSubmitting(true);
      setError(null);
      const hours = parsePositiveHours(expiresInHours);
      const response = await batchGrantDatasetGrants(
        selectedDatasetId,
        selectedGrantUserIds,
        hours,
      );
      await loadDatasetGrants(selectedDatasetId);
      setSelectedGrantUserIds([]);
      setAllMatchingUsersSelected(false);
      setAllMatchingUserCount(0);
      setExpiresInHours("");
      if ((response.failed || 0) > 0)
        setError(
          t("settings.permissionCenterModal.partialGrantWarning", {
            failed: response.failed,
          }),
        );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToGrantDatasetGrants"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevokeFromDataset = (permission: DatasetGrant) => {
    const userName =
      permission.user_nickname || permission.user_email || permission.user_id;
    const datasetName = selectedDataset?.dataset_name || permission.dataset_id;
    showConfirmDialog({
      title: t("settings.permissionCenterModal.revokePermission"),
      message: t("settings.permissionCenterModal.revokeDatasetGrantConfirm", {
        userName,
        datasetName,
      }),
      confirmText: t("settings.usersTab.revoke"),
      confirmVariant: "warning",
      onConfirm: async () => {
        closeConfirmDialog();
        try {
          setSubmitting(true);
          setError(null);
          const response = await batchRevokeDatasetGrants(
            permission.dataset_id,
            [permission.user_id],
          );
          await loadDatasetGrants(permission.dataset_id);
          if ((response.failed || 0) > 0)
            setError(
              t("settings.permissionCenterModal.partialRevokeWarning", {
                failed: response.failed,
              }),
            );
        } catch (err) {
          setError(
            err instanceof Error
              ? err.message
              : t("settings.permissionCenterModal.failedToRevokeDatasetGrant"),
          );
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const handleRevokeAllFromDataset = () => {
    if (!selectedDatasetId || validDatasetGrants.length === 0) return;
    showConfirmDialog({
      title: t("settings.permissionCenterModal.revokeAllPermissions"),
      message: t(
        "settings.permissionCenterModal.revokeAllDatasetGrantsConfirm",
        {
          datasetName: selectedDataset?.dataset_name || selectedDatasetId,
          count: validDatasetGrants.length,
        },
      ),
      confirmText: t("settings.permissionCenterModal.revokeAll"),
      confirmVariant: "danger",
      onConfirm: async () => {
        closeConfirmDialog();
        try {
          setSubmitting(true);
          setError(null);
          const response = await batchRevokeDatasetGrants(
            selectedDatasetId,
            validDatasetGrants.map((permission) => permission.user_id),
          );
          await loadDatasetGrants(selectedDatasetId);
          if ((response.failed || 0) > 0)
            setError(
              t("settings.permissionCenterModal.partialRevokeWarning", {
                failed: response.failed,
              }),
            );
        } catch (err) {
          setError(
            err instanceof Error
              ? err.message
              : t("settings.permissionCenterModal.failedToRevokeDatasetGrants"),
          );
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const handleToggleVisibilityDataset = (
    datasetId: string,
    checked: boolean,
  ) => {
    setSelectedVisibilityDatasetIds((prev) =>
      checked
        ? Array.from(new Set([...prev, datasetId]))
        : prev.filter((id) => id !== datasetId),
    );
  };

  const handleToggleAllVisibilityDatasets = (checked: boolean) => {
    const ids = pagedDatasets.map((dataset) => dataset.dataset_id);
    if (checked) {
      setSelectedVisibilityDatasetIds((prev) =>
        Array.from(new Set([...prev, ...ids])),
      );
      return;
    }
    const idSet = new Set(ids);
    setSelectedVisibilityDatasetIds((prev) =>
      prev.filter((id) => !idSet.has(id)),
    );
  };

  const allVisibleVisibilityDatasetsSelected =
    pagedDatasets.length > 0 &&
    pagedDatasets.every((dataset) =>
      selectedVisibilityDatasetIds.includes(dataset.dataset_id),
    );

  const handleBatchUpdateVisibility = async () => {
    if (selectedVisibilityDatasetIds.length === 0) return;
    try {
      setSubmitting(true);
      setError(null);
      const targetIsPublic = visibilityTarget === "public";
      const results = await Promise.allSettled(
        selectedVisibilityDatasetIds.map((datasetId) =>
          updateDatasetVisibility(datasetId, targetIsPublic),
        ),
      );
      const failedCount = results.filter(
        (result) => result.status === "rejected",
      ).length;
      if (failedCount > 0) {
        setError(
          t("settings.permissionCenterModal.partialVisibilityUpdateWarning", {
            failed: failedCount,
          }),
        );
      }
      setSelectedVisibilityDatasetIds([]);
      await loadDatasets();
      if (mode === "dataset" && selectedDatasetId) {
        await loadDatasetGrants(selectedDatasetId);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : t("settings.permissionCenterModal.failedToBatchUpdateVisibility"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const renderSegmentedSwitch = () => (
    <div className="mb-6 inline-flex rounded-2xl border border-gray-200 bg-gray-100 p-1">
      <button
        type="button"
        onClick={() => handleModeChange("user")}
        className={cn(
          "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all",
          mode === "user"
            ? "bg-gray-900 text-white shadow-sm"
            : "text-gray-600 hover:text-gray-900",
        )}
      >
        <Users className="h-4 w-4" />
        {t("settings.permissionCenterModal.byUser")}
      </button>
      <button
        type="button"
        onClick={() => handleModeChange("dataset")}
        className={cn(
          "flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all",
          mode === "dataset"
            ? "bg-gray-900 text-white shadow-sm"
            : "text-gray-600 hover:text-gray-900",
        )}
      >
        <Database className="h-4 w-4" />
        {t("settings.permissionCenterModal.byDataset")}
      </button>
    </div>
  );

  return (
    <ModalShell isOpen={true} onClose={onClose} maxWidth="6xl" className="p-6">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
              <Key className="h-5 w-5 text-primary-600" />
              {t("settings.permissionCenterModal.title")}
            </h3>
            <p className="mt-1 text-sm text-gray-500">
              {t("settings.permissionCenterModal.description")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 transition-colors hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {renderSegmentedSwitch()}
        {error && (
          <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {mode === "user" ? (
          <>
            <div className="mb-6 rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div className="flex-1">
                  <Label>
                    {t("settings.permissionCenterModal.userBrowser")}
                  </Label>
                  <div className="relative mt-2">
                    <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                    <Input
                      value={userSearchQuery}
                      onChange={(e) => {
                        setUserSearchQuery(e.target.value);
                        setUserPage(1);
                      }}
                      placeholder={t(
                        "settings.permissionCenterModal.searchUsers",
                      )}
                      className="pl-9"
                      disabled={submitting}
                    />
                  </div>
                </div>
                <div className="text-sm text-gray-500">
                  {t("settings.permissionCenterModal.userCount", {
                    count: userTotal,
                  })}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {loadingUsers ? (
                  <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.loadingUsers")}
                  </div>
                ) : userItems.length === 0 ? (
                  <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.noUsers")}
                  </div>
                ) : (
                  userItems.map((user) => {
                    const isSelected = user.id === selectedUserId;
                    return (
                      <button
                        key={user.id}
                        type="button"
                        onClick={() => {
                          setSelectedUserId(user.id);
                          setSelectedDatasetIds([]);
                          setAllMatchingDatasetsSelected(false);
                          setAllMatchingDatasetCount(0);
                          setExpiresInHours("");
                          setError(null);
                        }}
                        className={cn(
                          "rounded-xl border p-4 text-left transition-all",
                          isSelected
                            ? "border-gray-900 bg-gray-900 text-white shadow-md"
                            : "border-gray-200 bg-white hover:border-gray-300",
                        )}
                      >
                        <div className="truncate text-sm font-semibold">
                          {getUserDisplayName(user)}
                        </div>
                        <div
                          className={cn(
                            "mt-1 truncate text-xs",
                            isSelected ? "text-gray-300" : "text-gray-500",
                          )}
                        >
                          {user.email}
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                              isSelected
                                ? "border-white/20 bg-white/10 text-white"
                                : getRoleBadgeColor(user.role),
                            )}
                          >
                            {t(`settings.usersTab.role_${user.role}`)}
                          </span>
                          <span
                            className={cn(
                              "inline-flex items-center rounded px-2 py-0.5 text-xs",
                              isSelected
                                ? "bg-white/10 text-white"
                                : user.is_active
                                  ? "bg-green-100 text-green-700"
                                  : "bg-gray-200 text-gray-600",
                            )}
                          >
                            {user.is_active
                              ? t("settings.usersTab.active")
                              : t("settings.usersTab.inactive")}
                          </span>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
              <div className="mt-4">
                <PaginationFooter
                  page={userPage}
                  pageSize={userPageSize}
                  total={userTotal}
                  disabled={loadingUsers || submitting}
                  onPageChange={setUserPage}
                  onPageSizeChange={(pageSize) => {
                    setUserPageSize(pageSize);
                    setUserPage(1);
                  }}
                  t={t}
                />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-medium text-gray-900">
                      {t("settings.permissionCenterModal.currentPermissions")}
                    </h4>
                    <p className="mt-1 text-xs text-gray-500">
                      {selectedUser
                        ? t("settings.permissionCenterModal.selectedUserName", {
                            name: getUserDisplayName(selectedUser),
                          })
                        : t("settings.permissionCenterModal.selectUserHint")}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      {t(
                        "settings.permissionCenterModal.currentPermissionsCount",
                        { count: validUserPermissions.length },
                      )}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleRevokeAllFromUser}
                    disabled={
                      !selectedUser ||
                      validUserPermissions.length === 0 ||
                      submitting ||
                      loadingUserPermissions
                    }
                    className="text-red-600 hover:bg-red-50 hover:text-red-700"
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" />
                    {t("settings.permissionCenterModal.revokeAll")}
                  </Button>
                </div>
                {loadingUserPermissions ? (
                  <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.loadingUserPermissions")}
                  </div>
                ) : sortedUserPermissions.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.noCurrentPermissions")}
                  </div>
                ) : (
                  <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                    {sortedUserPermissions.map((permission) => (
                      <div
                        key={permission.id}
                        className={cn(
                          "flex items-start justify-between gap-3 rounded-xl border p-3",
                          permission.is_valid
                            ? "border-green-200 bg-green-50/40"
                            : "border-gray-200 bg-gray-50 opacity-70",
                        )}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-gray-900">
                            {permission.dataset_name || permission.dataset_id}
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                            <span className="inline-flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {permission.expires_at
                                ? t("settings.permissionModal.expires", {
                                    date: new Date(
                                      permission.expires_at,
                                    ).toLocaleString(),
                                  })
                                : t("settings.permissionModal.noExpiration")}
                            </span>
                            {!permission.is_valid && (
                              <span className="font-medium text-red-600">
                                {t("settings.permissionModal.expired")}
                              </span>
                            )}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {permission.can_read && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600">
                                <Eye className="h-3 w-3" />
                                {t("settings.permissionCenterModal.read")}
                              </span>
                            )}
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRevokeFromUser(permission)}
                          disabled={submitting}
                          className="h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-medium text-gray-900">
                      {t("settings.permissionCenterModal.grantDatasets")}
                    </h4>
                    <p className="mt-1 text-xs text-gray-500">
                      {selectedUser
                        ? t("settings.permissionCenterModal.selectedUserName", {
                            name: getUserDisplayName(selectedUser),
                          })
                        : t("settings.permissionCenterModal.selectUserHint")}
                    </p>
                  </div>
                  <div className="text-xs text-gray-500">
                    {t("settings.permissionCenterModal.datasetCount", {
                      count: datasetTotal,
                    })}
                  </div>
                </div>
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                  <Input
                    value={datasetSearchQuery}
                    onChange={(e) => {
                      setDatasetSearchQuery(e.target.value);
                      setGrantDatasetPage(1);
                    }}
                    placeholder={t(
                      "settings.permissionCenterModal.searchDatasets",
                    )}
                    className="pl-9"
                    disabled={submitting}
                  />
                </div>
                <div className="mb-4 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
                  <Checkbox
                    checked={allVisibleDatasetsSelected}
                    onCheckedChange={handleToggleAllDatasets}
                  />
                  <span className="text-sm text-gray-700">
                    {t("settings.permissionCenterModal.selectVisibleDatasets", {
                      count: selectableDatasetIdsOnPage.length,
                    })}
                  </span>
                </div>
                <BulkSelectionBanner
                  allPageSelected={allVisibleDatasetsSelected}
                  allMatchingSelected={allMatchingDatasetsSelected}
                  pageCount={selectableDatasetIdsOnPage.length}
                  selectedCount={
                    allMatchingDatasetsSelected
                      ? allMatchingDatasetCount
                      : selectedDatasetIds.length
                  }
                  selectingAll={selectingAllDatasets}
                  onSelectAllMatching={handleSelectAllMatchingDatasets}
                  onClearSelection={handleClearDatasetSelection}
                />
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {loadingDatasets ? (
                    <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                      {t("settings.permissionCenterModal.loadingDatasets")}
                    </div>
                  ) : pagedDatasets.length === 0 ? (
                    <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                      {t("settings.permissionCenterModal.noDatasets")}
                    </div>
                  ) : (
                    pagedDatasets.map((dataset) => {
                      const alreadyGranted = validUserDatasetIds.has(
                        dataset.dataset_id,
                      );
                      const isDatasetOwner =
                        dataset.user_id !== null &&
                        dataset.user_id === selectedUser?.id;
                      return (
                        <div
                          key={dataset.dataset_id}
                          className="rounded-xl border border-gray-200 bg-gray-50 p-4"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-semibold text-gray-900">
                                {dataset.dataset_name}
                              </div>
                              <div className="mt-1 text-xs text-gray-500">
                                {t(
                                  "settings.permissionCenterModal.datasetMeta",
                                  { count: dataset.file_count },
                                )}
                              </div>
                              <div className="mt-2">
                                {dataset.is_public ? (
                                  <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
                                    <Globe className="h-3 w-3" />
                                    {t(
                                      "settings.permissionCenterModal.publicDataset",
                                    )}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                                    <Lock className="h-3 w-3" />
                                    {t(
                                      "settings.permissionCenterModal.privateDataset",
                                    )}
                                  </span>
                                )}
                              </div>
                            </div>
                            <Checkbox
                              checked={selectedDatasetIds.includes(
                                dataset.dataset_id,
                              )}
                              disabled={
                                dataset.is_public ||
                                alreadyGranted ||
                                isDatasetOwner ||
                                submitting ||
                                !selectedUser
                              }
                              onCheckedChange={(checked) =>
                                handleToggleDataset(dataset.dataset_id, checked)
                              }
                            />
                          </div>
                          {isDatasetOwner && (
                            <div className="mt-3 inline-flex rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                              {t("settings.permissionCenterModal.datasetOwner")}
                            </div>
                          )}
                          {!isDatasetOwner && alreadyGranted && (
                            <div className="mt-3 inline-flex rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
                              {t(
                                "settings.permissionCenterModal.alreadyGranted",
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
                <div className="mt-4">
                  <PaginationFooter
                    page={grantDatasetPage}
                    pageSize={grantDatasetPageSize}
                    total={datasetTotal}
                    disabled={loadingDatasets || submitting}
                    onPageChange={setGrantDatasetPage}
                    onPageSizeChange={(pageSize) => {
                      setGrantDatasetPageSize(pageSize);
                      setGrantDatasetPage(1);
                    }}
                    t={t}
                  />
                </div>
                <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-800">
                    <Lock className="h-4 w-4 text-amber-600" />
                    {t(
                      "settings.permissionCenterModal.privateTempVisibilityOnly",
                    )}
                  </div>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <div className="sm:w-48">
                      <Label className="mb-1.5 block text-xs text-gray-500">
                        {t("settings.permissionModal.expirationHours")}
                      </Label>
                      <Input
                        type="number"
                        min="1"
                        value={expiresInHours}
                        onChange={(e) => setExpiresInHours(e.target.value)}
                        placeholder={t("settings.permissionModal.forever")}
                        disabled={submitting || !selectedUser}
                      />
                    </div>
                    <div className="flex-1 text-xs text-gray-400">
                      {t("settings.permissionModal.leaveEmptyForPermanent")}
                    </div>
                    <Button
                      type="button"
                      onClick={handleGrantToUser}
                      disabled={
                        selectedGrantableDatasetIds.length === 0 ||
                        !selectedUser ||
                        submitting
                      }
                      className="bg-purple-600 hover:bg-purple-700"
                    >
                      {submitting
                        ? t("settings.permissionCenterModal.granting")
                        : t(
                            "settings.permissionCenterModal.grantSelectedDatasets",
                            { count: selectedGrantableDatasetIds.length },
                          )}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="mb-6 rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div className="flex-1">
                  <Label>
                    {t("settings.permissionCenterModal.datasetBrowser")}
                  </Label>
                  <div className="relative mt-2">
                    <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                    <Input
                      value={datasetSearchQuery}
                      onChange={(e) => {
                        setDatasetSearchQuery(e.target.value);
                        setDatasetPage(1);
                      }}
                      placeholder={t(
                        "settings.permissionCenterModal.searchDatasets",
                      )}
                      className="pl-9"
                      disabled={submitting}
                    />
                  </div>
                </div>
                <div className="text-sm text-gray-500">
                  {t("settings.permissionCenterModal.datasetCount", {
                    count: datasetTotal,
                  })}
                </div>
              </div>
              <div className="mb-4 rounded-xl border border-gray-200 bg-white p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-800">
                    <ArrowRightLeft className="h-4 w-4 text-primary-600" />
                    {t("settings.permissionCenterModal.bulkDatasetVisibility")}
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={visibilityTarget}
                      onChange={(value) =>
                        setVisibilityTarget(value as "public" | "private")
                      }
                      options={[
                        {
                          value: "public",
                          label: t("settings.permissionCenterModal.setPublic"),
                        },
                        {
                          value: "private",
                          label: t("settings.permissionCenterModal.setPrivate"),
                        },
                      ]}
                      className="w-40"
                      disabled={submitting}
                    />
                    <Button
                      type="button"
                      size="sm"
                      onClick={handleBatchUpdateVisibility}
                      disabled={
                        selectedVisibilityDatasetIds.length === 0 || submitting
                      }
                    >
                      {t(
                        "settings.permissionCenterModal.applyToSelectedDatasets",
                        { count: selectedVisibilityDatasetIds.length },
                      )}
                    </Button>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={allVisibleVisibilityDatasetsSelected}
                    onCheckedChange={handleToggleAllVisibilityDatasets}
                  />
                  <span className="text-sm text-gray-700">
                    {t(
                      "settings.permissionCenterModal.selectVisibleDatasetsForVisibility",
                      { count: pagedDatasets.length },
                    )}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {loadingDatasets ? (
                  <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.loadingDatasets")}
                  </div>
                ) : pagedDatasets.length === 0 ? (
                  <div className="col-span-full rounded-xl border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.noDatasets")}
                  </div>
                ) : (
                  pagedDatasets.map((dataset) => {
                    const isSelected = selectedDatasetId === dataset.dataset_id;
                    return (
                      <div
                        key={dataset.dataset_id}
                        className={cn(
                          "rounded-xl border p-4 transition-all",
                          isSelected
                            ? "border-gray-900 bg-gray-900 text-white shadow-md"
                            : "border-gray-200 bg-white hover:border-gray-300",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedDatasetId(dataset.dataset_id);
                              setSelectedGrantUserIds([]);
                              setAllMatchingUsersSelected(false);
                              setAllMatchingUserCount(0);
                              setExpiresInHours("");
                              setError(null);
                            }}
                            className="min-w-0 flex-1 text-left"
                          >
                            <div className="truncate text-sm font-semibold">
                              {dataset.dataset_name}
                            </div>
                            <div
                              className={cn(
                                "mt-1 text-xs",
                                isSelected ? "text-gray-300" : "text-gray-500",
                              )}
                            >
                              {t("settings.permissionCenterModal.datasetMeta", {
                                count: dataset.file_count,
                              })}
                            </div>
                            <div className="mt-2">
                              {dataset.is_public ? (
                                <span
                                  className={cn(
                                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                                    isSelected
                                      ? "bg-white/20 text-white"
                                      : "bg-sky-100 text-sky-700",
                                  )}
                                >
                                  <Globe className="h-3 w-3" />
                                  {t(
                                    "settings.permissionCenterModal.publicDataset",
                                  )}
                                </span>
                              ) : (
                                <span
                                  className={cn(
                                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                                    isSelected
                                      ? "bg-white/20 text-white"
                                      : "bg-amber-100 text-amber-700",
                                  )}
                                >
                                  <Lock className="h-3 w-3" />
                                  {t(
                                    "settings.permissionCenterModal.privateDataset",
                                  )}
                                </span>
                              )}
                            </div>
                          </button>
                          <Checkbox
                            checked={selectedVisibilityDatasetIds.includes(
                              dataset.dataset_id,
                            )}
                            onCheckedChange={(checked) =>
                              handleToggleVisibilityDataset(
                                dataset.dataset_id,
                                checked,
                              )
                            }
                            disabled={submitting}
                          />
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
              <div className="mt-4">
                <PaginationFooter
                  page={datasetPage}
                  pageSize={datasetPageSize}
                  total={datasetTotal}
                  disabled={loadingDatasets || submitting}
                  onPageChange={setDatasetPage}
                  onPageSizeChange={(pageSize) => {
                    setDatasetPageSize(pageSize);
                    setDatasetPage(1);
                  }}
                  t={t}
                />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-medium text-gray-900">
                      {t("settings.permissionCenterModal.currentAccess")}
                    </h4>
                    <p className="mt-1 text-xs text-gray-500">
                      {selectedDataset
                        ? t(
                            "settings.permissionCenterModal.selectedDatasetName",
                            { name: selectedDataset.dataset_name },
                          )
                        : t("settings.permissionCenterModal.selectDatasetHint")}
                    </p>
                    {selectedDatasetIsPublic ? (
                      <p className="mt-1 text-xs text-amber-700">
                        {t(
                          "settings.permissionCenterModal.publicDatasetGrantDisabled",
                        )}
                      </p>
                    ) : (
                      <p className="mt-1 text-xs text-gray-500">
                        {t("settings.permissionCenterModal.currentAccessCount", {
                          count: validDatasetGrants.length,
                        })}
                      </p>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleRevokeAllFromDataset}
                    disabled={
                      !selectedDatasetId ||
                      validDatasetGrants.length === 0 ||
                      submitting ||
                      loadingDatasetGrants
                    }
                    className="text-red-600 hover:bg-red-50 hover:text-red-700"
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" />
                    {t("settings.permissionCenterModal.revokeAll")}
                  </Button>
                </div>
                {loadingDatasetGrants ? (
                  <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.loadingDatasetGrants")}
                  </div>
                ) : selectedDatasetIsPublic ? (
                  <div className="rounded-xl border border-dashed border-amber-200 bg-amber-50/60 px-4 py-8 text-center text-sm text-amber-700">
                    {t(
                      "settings.permissionCenterModal.publicDatasetGrantDisabled",
                    )}
                  </div>
                ) : sortedDatasetGrants.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                    {t("settings.permissionCenterModal.noCurrentAccess")}
                  </div>
                ) : (
                  <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                    {sortedDatasetGrants.map((permission) => {
                      const displayName =
                        permission.user_nickname ||
                        permission.user_email ||
                        permission.user_id;
                      return (
                        <div
                          key={permission.id}
                          className={cn(
                            "flex items-start justify-between gap-3 rounded-xl border p-3",
                            permission.is_valid
                              ? "border-green-200 bg-green-50/40"
                              : "border-gray-200 bg-gray-50 opacity-70",
                          )}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium text-gray-900">
                              {displayName}
                            </div>
                            {permission.user_email && (
                              <div className="mt-1 truncate text-xs text-gray-500">
                                {permission.user_email}
                              </div>
                            )}
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              {permission.user_role && (
                                <span
                                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getRoleBadgeColor(permission.user_role)}`}
                                >
                                  {t(
                                    `settings.usersTab.role_${permission.user_role}`,
                                  )}
                                </span>
                              )}
                              {typeof permission.user_is_active ===
                                "boolean" && (
                                <span
                                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs ${permission.user_is_active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-600"}`}
                                >
                                  {permission.user_is_active
                                    ? t("settings.usersTab.active")
                                    : t("settings.usersTab.inactive")}
                                </span>
                              )}
                              <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                                <Clock className="h-3 w-3" />
                                {permission.expires_at
                                  ? t("settings.permissionModal.expires", {
                                      date: new Date(
                                        permission.expires_at,
                                      ).toLocaleString(),
                                    })
                                  : t("settings.permissionModal.noExpiration")}
                              </span>
                              {!permission.is_valid && (
                                <span className="text-xs font-medium text-red-600">
                                  {t("settings.permissionModal.expired")}
                                </span>
                              )}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {permission.can_read && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600">
                                  <Eye className="h-3 w-3" />
                                  {t("settings.permissionCenterModal.read")}
                                </span>
                              )}
                            </div>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRevokeFromDataset(permission)}
                            disabled={submitting}
                            className="h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-medium text-gray-900">
                      {t("settings.permissionCenterModal.grantUsers")}
                    </h4>
                    <p className="mt-1 text-xs text-gray-500">
                      {selectedDataset
                        ? t(
                            "settings.permissionCenterModal.selectedDatasetName",
                            { name: selectedDataset.dataset_name },
                          )
                        : t("settings.permissionCenterModal.selectDatasetHint")}
                    </p>
                    {selectedDatasetIsPublic && (
                      <p className="mt-1 text-xs text-amber-700">
                        {t(
                          "settings.permissionCenterModal.publicDatasetGrantDisabled",
                        )}
                      </p>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">
                    {t("settings.permissionCenterModal.userCount", {
                      count: grantUserTotal,
                    })}
                  </div>
                </div>
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                  <Input
                    value={grantUserSearchQuery}
                    onChange={(e) => {
                      setGrantUserSearchQuery(e.target.value);
                      setGrantUserPage(1);
                    }}
                    placeholder={t(
                      "settings.permissionCenterModal.searchUsers",
                    )}
                    className="pl-9"
                    disabled={submitting || selectedDatasetIsPublic}
                  />
                </div>
                <div className="mb-4 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
                  <Checkbox
                    checked={allVisibleUsersSelected}
                    onCheckedChange={handleToggleAllUsers}
                    disabled={selectedDatasetIsPublic}
                  />
                  <span className="text-sm text-gray-700">
                    {t("settings.permissionCenterModal.selectVisibleUsers", {
                      count: selectableGrantUsers.length,
                    })}
                  </span>
                </div>
                <BulkSelectionBanner
                  allPageSelected={allVisibleUsersSelected}
                  allMatchingSelected={allMatchingUsersSelected}
                  pageCount={selectableGrantUsers.length}
                  selectedCount={
                    allMatchingUsersSelected
                      ? allMatchingUserCount
                      : selectedGrantUserIds.length
                  }
                  selectingAll={selectingAllUsers}
                  onSelectAllMatching={handleSelectAllMatchingUsers}
                  onClearSelection={handleClearUserSelection}
                />
                <div className="space-y-2">
                  {loadingGrantUsers ? (
                    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                      {t("settings.permissionCenterModal.loadingUsers")}
                    </div>
                  ) : grantUserItems.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
                      {t("settings.permissionCenterModal.noUsers")}
                    </div>
                  ) : (
                    <div className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
                      {grantUserItems.map((user) => {
                        const alreadyGranted = validDatasetGrantUserIds.has(
                          user.id,
                        );
                        const isDatasetOwner =
                          selectedDataset?.user_id !== null &&
                          user.id === selectedDataset?.user_id;
                        return (
                          <div
                            key={user.id}
                            className="flex items-start gap-3 rounded-xl border border-gray-200 bg-gray-50 p-3"
                          >
                            <Checkbox
                              checked={selectedGrantUserIds.includes(user.id)}
                              disabled={
                                alreadyGranted ||
                                isDatasetOwner ||
                                submitting ||
                                !selectedDatasetId ||
                                selectedDatasetIsPublic
                              }
                              onCheckedChange={(checked) =>
                                handleToggleGrantUser(user.id, checked)
                              }
                            />
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-medium text-gray-900">
                                {getUserDisplayName(user)}
                              </div>
                              <div className="mt-1 truncate text-xs text-gray-500">
                                {user.email}
                              </div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <span
                                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${getRoleBadgeColor(user.role)}`}
                                >
                                  {t(`settings.usersTab.role_${user.role}`)}
                                </span>
                                <span
                                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs ${user.is_active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-600"}`}
                                >
                                  {user.is_active
                                    ? t("settings.usersTab.active")
                                    : t("settings.usersTab.inactive")}
                                </span>
                                {isDatasetOwner && (
                                  <span className="inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                                    {t(
                                      "settings.permissionCenterModal.datasetOwner",
                                    )}
                                  </span>
                                )}
                                {!isDatasetOwner && alreadyGranted && (
                                  <span className="inline-flex rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                                    {t(
                                      "settings.permissionCenterModal.alreadyGranted",
                                    )}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="mt-4">
                  <PaginationFooter
                    page={grantUserPage}
                    pageSize={grantUserPageSize}
                    total={grantUserTotal}
                    disabled={loadingGrantUsers || submitting}
                    onPageChange={setGrantUserPage}
                    onPageSizeChange={(pageSize) => {
                      setGrantUserPageSize(pageSize);
                      setGrantUserPage(1);
                    }}
                    t={t}
                  />
                </div>
                <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-800">
                    <Lock className="h-4 w-4 text-amber-600" />
                    {t(
                      "settings.permissionCenterModal.privateTempVisibilityOnly",
                    )}
                  </div>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <div className="sm:w-48">
                      <Label className="mb-1.5 block text-xs text-gray-500">
                        {t("settings.permissionModal.expirationHours")}
                      </Label>
                      <Input
                        type="number"
                        min="1"
                        value={expiresInHours}
                        onChange={(e) => setExpiresInHours(e.target.value)}
                        placeholder={t("settings.permissionModal.forever")}
                        disabled={
                          submitting ||
                          !selectedDatasetId ||
                          selectedDatasetIsPublic
                        }
                      />
                    </div>
                    <div className="flex-1 text-xs text-gray-400">
                      {t("settings.permissionModal.leaveEmptyForPermanent")}
                    </div>
                    <Button
                      type="button"
                      onClick={handleGrantToDataset}
                      disabled={
                        !selectedDatasetId ||
                        selectedGrantUserIds.length === 0 ||
                        submitting ||
                        selectedDatasetIsPublic
                      }
                      className="bg-purple-600 hover:bg-purple-700"
                    >
                      {submitting
                        ? t("settings.permissionCenterModal.granting")
                        : t(
                            "settings.permissionCenterModal.grantSelectedUsers",
                            { count: selectedGrantUserIds.length },
                          )}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
        <div className="mt-6 flex justify-end border-t border-gray-200 pt-4">
          <Button type="button" variant="outline" onClick={onClose}>
            {t("settings.permissionModal.close")}
          </Button>
        </div>
    </ModalShell>
  );
}
