import { useCallback, useEffect, useMemo, useState } from "react";
import { useAsyncAction } from "../../lib/useAsyncAction";
import { useDebounce } from "../../lib/useDebounce";
import { useTranslation } from "react-i18next";
import { ModalShell } from "../ui/modal-shell";
import { Database, Key, Users, X } from "lucide-react";
import { Button } from "../ui/button";
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
import { PermissionUserPanel } from "./PermissionUserPanel";
import { PermissionDatasetPanel } from "./PermissionDatasetPanel";

type PermissionMode = "user" | "dataset";
type PermissionDataset = DatasetSummary & { dataset_id: string };

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

export function PermissionCenterModal({
  showConfirmDialog,
  closeConfirmDialog,
  onClose,
  initialMode = "user",
  onModeChange,
}: PermissionCenterModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<PermissionMode>(initialMode);
  const [submitting, runSubmitting, asyncError, clearAsyncError] = useAsyncAction<void>({ withError: true });
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const error = asyncError || loadingError;
  const clearError = () => {
    clearAsyncError();
    setLoadingError(null);
  };
  const setError = (msg: string | null) => {
    if (msg === null) {
      setLoadingError(null);
    } else {
      setLoadingError(msg);
    }
  };
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
    clearError();
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
      clearError();
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
      clearError();
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

  const handleGrantToUser = () => {
    if (!selectedUser || selectedGrantableDatasetIds.length === 0) return;
    clearError();
    void runSubmitting(async () => {
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
    });
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
        clearError();
        void runSubmitting(async () => {
          await revokeDatasetGrant(permission.dataset_id, selectedUser.id);
          await loadUserPermissions(selectedUser.id);
        });
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
        clearError();
        void runSubmitting(async () => {
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
        });
      },
    });
  };

  const handleGrantToDataset = () => {
    if (
      !selectedDatasetId ||
      selectedGrantUserIds.length === 0 ||
      selectedDatasetIsPublic
    )
      return;
    clearError();
    void runSubmitting(async () => {
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
    });
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
        clearError();
        void runSubmitting(async () => {
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
        });
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
        clearError();
        void runSubmitting(async () => {
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
        });
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

  const handleBatchUpdateVisibility = () => {
    if (selectedVisibilityDatasetIds.length === 0) return;
    clearError();
    void runSubmitting(async () => {
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
    });
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
          <PermissionUserPanel
            submitting={submitting}
            clearError={clearError}
            expiresInHours={expiresInHours}
            onExpiresInHoursChange={setExpiresInHours}
            userSearchQuery={userSearchQuery}
            onUserSearchChange={setUserSearchQuery}
            userPage={userPage}
            userPageSize={userPageSize}
            onUserPageChange={setUserPage}
            onUserPageSizeChange={setUserPageSize}
            userTotal={userTotal}
            loadingUsers={loadingUsers}
            userItems={userItems}
            selectedUserId={selectedUserId}
            selectedUser={selectedUser}
            onSelectUserWithReset={(userId) => {
              setSelectedUserId(userId);
              setSelectedDatasetIds([]);
              setAllMatchingDatasetsSelected(false);
              setAllMatchingDatasetCount(0);
              setExpiresInHours("");
              clearError();
            }}
            loadingUserPermissions={loadingUserPermissions}
            sortedUserPermissions={sortedUserPermissions}
            validUserPermissions={validUserPermissions}
            onRevokeFromUser={handleRevokeFromUser}
            onRevokeAllFromUser={handleRevokeAllFromUser}
            datasetSearchQuery={datasetSearchQuery}
            onDatasetSearchChange={setDatasetSearchQuery}
            grantDatasetPage={grantDatasetPage}
            grantDatasetPageSize={grantDatasetPageSize}
            onGrantDatasetPageChange={setGrantDatasetPage}
            onGrantDatasetPageSizeChange={setGrantDatasetPageSize}
            datasetTotal={datasetTotal}
            loadingDatasets={loadingDatasets}
            pagedDatasets={pagedDatasets}
            validUserDatasetIds={validUserDatasetIds}
            selectedDatasetIds={selectedDatasetIds}
            selectableDatasetIdsOnPage={selectableDatasetIdsOnPage}
            allVisibleDatasetsSelected={allVisibleDatasetsSelected}
            selectedGrantableDatasetIds={selectedGrantableDatasetIds}
            allMatchingDatasetsSelected={allMatchingDatasetsSelected}
            allMatchingDatasetCount={allMatchingDatasetCount}
            selectingAllDatasets={selectingAllDatasets}
            onToggleDataset={handleToggleDataset}
            onToggleAllDatasets={handleToggleAllDatasets}
            onSelectAllMatchingDatasets={handleSelectAllMatchingDatasets}
            onClearDatasetSelection={handleClearDatasetSelection}
            onGrantToUser={handleGrantToUser}
          />
        ) : (
          <PermissionDatasetPanel
            submitting={submitting}
            clearError={clearError}
            expiresInHours={expiresInHours}
            onExpiresInHoursChange={setExpiresInHours}
            datasetSearchQuery={datasetSearchQuery}
            onDatasetSearchChange={setDatasetSearchQuery}
            datasetPage={datasetPage}
            datasetPageSize={datasetPageSize}
            onDatasetPageChange={setDatasetPage}
            onDatasetPageSizeChange={setDatasetPageSize}
            datasetTotal={datasetTotal}
            loadingDatasets={loadingDatasets}
            pagedDatasets={pagedDatasets}
            selectedDatasetId={selectedDatasetId}
            selectedDataset={selectedDataset}
            selectedDatasetIsPublic={selectedDatasetIsPublic}
            onSelectDatasetWithReset={(datasetId) => {
              setSelectedDatasetId(datasetId);
              setSelectedGrantUserIds([]);
              setAllMatchingUsersSelected(false);
              setAllMatchingUserCount(0);
              setExpiresInHours("");
              clearError();
            }}
            loadingDatasetGrants={loadingDatasetGrants}
            sortedDatasetGrants={sortedDatasetGrants}
            validDatasetGrants={validDatasetGrants}
            onRevokeFromDataset={handleRevokeFromDataset}
            onRevokeAllFromDataset={handleRevokeAllFromDataset}
            visibilityTarget={visibilityTarget}
            onVisibilityTargetChange={setVisibilityTarget}
            selectedVisibilityDatasetIds={selectedVisibilityDatasetIds}
            allVisibleVisibilityDatasetsSelected={allVisibleVisibilityDatasetsSelected}
            onToggleVisibilityDataset={handleToggleVisibilityDataset}
            onToggleAllVisibilityDatasets={handleToggleAllVisibilityDatasets}
            onBatchUpdateVisibility={handleBatchUpdateVisibility}
            grantUserSearchQuery={grantUserSearchQuery}
            onGrantUserSearchChange={setGrantUserSearchQuery}
            grantUserPage={grantUserPage}
            grantUserPageSize={grantUserPageSize}
            onGrantUserPageChange={setGrantUserPage}
            onGrantUserPageSizeChange={setGrantUserPageSize}
            grantUserTotal={grantUserTotal}
            loadingGrantUsers={loadingGrantUsers}
            grantUserItems={grantUserItems}
            selectableGrantUsers={selectableGrantUsers}
            selectedGrantUserIds={selectedGrantUserIds}
            validDatasetGrantUserIds={validDatasetGrantUserIds}
            allVisibleUsersSelected={allVisibleUsersSelected}
            allMatchingUsersSelected={allMatchingUsersSelected}
            allMatchingUserCount={allMatchingUserCount}
            selectingAllUsers={selectingAllUsers}
            onToggleGrantUser={handleToggleGrantUser}
            onToggleAllUsers={handleToggleAllUsers}
            onSelectAllMatchingUsers={handleSelectAllMatchingUsers}
            onClearUserSelection={handleClearUserSelection}
            onGrantToDataset={handleGrantToDataset}
          />
        )}
        <div className="mt-6 flex justify-end border-t border-gray-200 pt-4">
          <Button type="button" variant="outline" onClick={onClose}>
            {t("settings.permissionModal.close")}
          </Button>
        </div>
    </ModalShell>
  );
}
