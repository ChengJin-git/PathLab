import { useTranslation } from "react-i18next";
import { Clock, Globe, Lock, Search, Trash2 } from "lucide-react";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { PaginationFooter } from "../ui/pagination-footer";
import { cn } from "../../lib/utils";
import type { DatasetGrant } from "../../api/grants";
import type { UserListItem } from "../../api/users";
import type { DatasetSummary } from "../../api/wsi";
import { BulkSelectionBanner } from "./BulkSelectionBanner";

type PermissionDataset = DatasetSummary & { dataset_id: string };

function getRoleBadgeColor(role: string) {
  switch (role) {
    case "admin": return "bg-red-100 text-red-800 border-red-200";
    case "pathologist": return "bg-primary-100 text-primary-800 border-primary-200";
    case "guest": return "bg-gray-100 text-gray-800 border-gray-200";
    default: return "bg-gray-100 text-gray-800 border-gray-200";
  }
}

function getUserDisplayName(user?: Partial<{ nickname?: string | null; username?: string | null; email?: string | null }> | null) {
  return user?.nickname || user?.username || user?.email || "-";
}

export interface PermissionUserPanelProps {
  submitting: boolean;
  clearError: () => void;
  expiresInHours: string;
  onExpiresInHoursChange: (value: string) => void;
  userSearchQuery: string;
  onUserSearchChange: (q: string) => void;
  userPage: number;
  userPageSize: number;
  onUserPageChange: (page: number) => void;
  onUserPageSizeChange: (pageSize: number) => void;
  userTotal: number;
  loadingUsers: boolean;
  userItems: UserListItem[];
  selectedUserId: string;
  selectedUser: UserListItem | null;
  onSelectUserWithReset: (userId: string) => void;
  loadingUserPermissions: boolean;
  sortedUserPermissions: DatasetGrant[];
  validUserPermissions: DatasetGrant[];
  onRevokeFromUser: (permission: DatasetGrant) => void;
  onRevokeAllFromUser: () => void;
  datasetSearchQuery: string;
  onDatasetSearchChange: (q: string) => void;
  grantDatasetPage: number;
  grantDatasetPageSize: number;
  onGrantDatasetPageChange: (page: number) => void;
  onGrantDatasetPageSizeChange: (pageSize: number) => void;
  datasetTotal: number;
  loadingDatasets: boolean;
  pagedDatasets: PermissionDataset[];
  validUserDatasetIds: Set<string>;
  selectedDatasetIds: string[];
  selectableDatasetIdsOnPage: string[];
  allVisibleDatasetsSelected: boolean;
  selectedGrantableDatasetIds: string[];
  allMatchingDatasetsSelected: boolean;
  allMatchingDatasetCount: number;
  selectingAllDatasets: boolean;
  onToggleDataset: (datasetId: string, checked: boolean) => void;
  onToggleAllDatasets: (checked: boolean) => void;
  onSelectAllMatchingDatasets: () => Promise<void>;
  onClearDatasetSelection: () => void;
  onGrantToUser: () => void;
}

export function PermissionUserPanel({
  submitting,
  expiresInHours,
  onExpiresInHoursChange,
  userSearchQuery,
  onUserSearchChange,
  userPage,
  userPageSize,
  onUserPageChange,
  onUserPageSizeChange,
  userTotal,
  loadingUsers,
  userItems,
  selectedUserId,
  selectedUser,
  onSelectUserWithReset,
  loadingUserPermissions,
  sortedUserPermissions,
  validUserPermissions,
  onRevokeFromUser,
  onRevokeAllFromUser,
  datasetSearchQuery,
  onDatasetSearchChange,
  grantDatasetPage,
  grantDatasetPageSize,
  onGrantDatasetPageChange,
  onGrantDatasetPageSizeChange,
  datasetTotal,
  loadingDatasets,
  pagedDatasets,
  validUserDatasetIds,
  selectedDatasetIds,
  selectableDatasetIdsOnPage,
  allVisibleDatasetsSelected,
  selectedGrantableDatasetIds,
  allMatchingDatasetsSelected,
  allMatchingDatasetCount,
  selectingAllDatasets,
  onToggleDataset,
  onToggleAllDatasets,
  onSelectAllMatchingDatasets,
  onClearDatasetSelection,
  onGrantToUser,
}: PermissionUserPanelProps) {
  const { t } = useTranslation();

  return (
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
                  onUserSearchChange(e.target.value);
                  onUserPageChange(1);
                }}
                placeholder={t("settings.permissionCenterModal.searchUsers")}
                className="pl-9"
                disabled={submitting}
              />
            </div>
          </div>
          <div className="text-sm text-gray-500">
            {t("settings.permissionCenterModal.userCount", { count: userTotal })}
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
                  onClick={() => onSelectUserWithReset(user.id)}
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
                    {user.username || user.email || "-"}
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
            onPageChange={onUserPageChange}
            onPageSizeChange={(pageSize) => {
              onUserPageSizeChange(pageSize);
              onUserPageChange(1);
            }}
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
                {t("settings.permissionCenterModal.currentPermissionsCount", {
                  count: validUserPermissions.length,
                })}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onRevokeAllFromUser}
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
                      {(permission.dataset_name || permission.dataset_id).trim()}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {permission.expires_at
                          ? t("settings.permissionModal.expires", {
                              date: new Date(permission.expires_at).toLocaleString(),
                            })
                          : t("settings.permissionModal.noExpiration")}
                      </span>
                      {!permission.is_valid && (
                        <span className="font-medium text-red-600">
                          {t("settings.permissionModal.expired")}
                        </span>
                      )}
                    </div>

                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onRevokeFromUser(permission)}
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
              {t("settings.permissionCenterModal.datasetCount", { count: datasetTotal })}
            </div>
          </div>
          <div className="relative mb-3">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
            <Input
              value={datasetSearchQuery}
              onChange={(e) => {
                onDatasetSearchChange(e.target.value);
                onGrantDatasetPageChange(1);
              }}
              placeholder={t("settings.permissionCenterModal.searchDatasets")}
              className="pl-9"
              disabled={submitting}
            />
          </div>
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
            <Checkbox
              checked={allVisibleDatasetsSelected}
              onCheckedChange={onToggleAllDatasets}
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
            onSelectAllMatching={onSelectAllMatchingDatasets}
            onClearSelection={onClearDatasetSelection}
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
                const alreadyGranted = validUserDatasetIds.has(dataset.dataset_id);
                const isDatasetOwner =
                  dataset.user_id !== null && dataset.user_id === selectedUser?.id;
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
                          {t("settings.permissionCenterModal.datasetMeta", {
                            count: dataset.file_count,
                          })}
                        </div>
                        <div className="mt-2">
                          {dataset.is_public ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
                              <Globe className="h-3 w-3" />
                              {t("settings.permissionCenterModal.publicDataset")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                              <Lock className="h-3 w-3" />
                              {t("settings.permissionCenterModal.privateDataset")}
                            </span>
                          )}
                        </div>
                      </div>
                      <Checkbox
                        checked={selectedDatasetIds.includes(dataset.dataset_id)}
                        disabled={
                          dataset.is_public ||
                          alreadyGranted ||
                          isDatasetOwner ||
                          submitting ||
                          !selectedUser
                        }
                        onCheckedChange={(checked) =>
                          onToggleDataset(dataset.dataset_id, checked)
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
                        {t("settings.permissionCenterModal.alreadyGranted")}
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
              onPageChange={onGrantDatasetPageChange}
              onPageSizeChange={(pageSize) => {
                onGrantDatasetPageSizeChange(pageSize);
                onGrantDatasetPageChange(1);
              }}
            />
          </div>
          <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-800">
              <Lock className="h-4 w-4 text-amber-600" />
              {t("settings.permissionCenterModal.privateTempVisibilityOnly")}
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
                  onChange={(e) => onExpiresInHoursChange(e.target.value)}
                  placeholder={t("settings.permissionModal.forever")}
                  disabled={submitting || !selectedUser}
                />
              </div>
              <div className="flex-1 text-xs text-gray-400">
                {t("settings.permissionModal.leaveEmptyForPermanent")}
              </div>
              <Button
                type="button"
                onClick={onGrantToUser}
                disabled={
                  selectedGrantableDatasetIds.length === 0 ||
                  !selectedUser ||
                  submitting
                }
                className="bg-purple-600 hover:bg-purple-700"
              >
                {submitting
                  ? t("settings.permissionCenterModal.granting")
                  : t("settings.permissionCenterModal.grantSelectedDatasets", {
                      count: selectedGrantableDatasetIds.length,
                    })}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
