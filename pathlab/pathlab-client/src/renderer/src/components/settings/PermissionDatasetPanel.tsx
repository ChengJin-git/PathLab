import { useTranslation } from "react-i18next";
import { ArrowRightLeft, Clock, Globe, Lock, Search, Trash2 } from "lucide-react";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select } from "../ui/select";
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

function getUserDisplayName(user?: Partial<{ nickname?: string; email?: string }> | null) {
  return user?.nickname || user?.email || "-";
}

export interface PermissionDatasetPanelProps {
  submitting: boolean;
  clearError: () => void;
  expiresInHours: string;
  onExpiresInHoursChange: (value: string) => void;
  datasetSearchQuery: string;
  onDatasetSearchChange: (q: string) => void;
  datasetPage: number;
  datasetPageSize: number;
  onDatasetPageChange: (page: number) => void;
  onDatasetPageSizeChange: (pageSize: number) => void;
  datasetTotal: number;
  loadingDatasets: boolean;
  pagedDatasets: PermissionDataset[];
  selectedDatasetId: string;
  selectedDataset: PermissionDataset | null;
  selectedDatasetIsPublic: boolean;
  onSelectDatasetWithReset: (datasetId: string) => void;
  loadingDatasetGrants: boolean;
  sortedDatasetGrants: DatasetGrant[];
  validDatasetGrants: DatasetGrant[];
  onRevokeFromDataset: (permission: DatasetGrant) => void;
  onRevokeAllFromDataset: () => void;
  visibilityTarget: "public" | "private";
  onVisibilityTargetChange: (value: "public" | "private") => void;
  selectedVisibilityDatasetIds: string[];
  allVisibleVisibilityDatasetsSelected: boolean;
  onToggleVisibilityDataset: (datasetId: string, checked: boolean) => void;
  onToggleAllVisibilityDatasets: (checked: boolean) => void;
  onBatchUpdateVisibility: () => void;
  grantUserSearchQuery: string;
  onGrantUserSearchChange: (q: string) => void;
  grantUserPage: number;
  grantUserPageSize: number;
  onGrantUserPageChange: (page: number) => void;
  onGrantUserPageSizeChange: (pageSize: number) => void;
  grantUserTotal: number;
  loadingGrantUsers: boolean;
  grantUserItems: UserListItem[];
  selectableGrantUsers: UserListItem[];
  selectedGrantUserIds: string[];
  validDatasetGrantUserIds: Set<string>;
  allVisibleUsersSelected: boolean;
  allMatchingUsersSelected: boolean;
  allMatchingUserCount: number;
  selectingAllUsers: boolean;
  onToggleGrantUser: (userId: string, checked: boolean) => void;
  onToggleAllUsers: (checked: boolean) => void;
  onSelectAllMatchingUsers: () => Promise<void>;
  onClearUserSelection: () => void;
  onGrantToDataset: () => void;
}

export function PermissionDatasetPanel({
  submitting,
  expiresInHours,
  onExpiresInHoursChange,
  datasetSearchQuery,
  onDatasetSearchChange,
  datasetPage,
  datasetPageSize,
  onDatasetPageChange,
  onDatasetPageSizeChange,
  datasetTotal,
  loadingDatasets,
  pagedDatasets,
  selectedDatasetId,
  selectedDataset,
  selectedDatasetIsPublic,
  onSelectDatasetWithReset,
  loadingDatasetGrants,
  sortedDatasetGrants,
  validDatasetGrants,
  onRevokeFromDataset,
  onRevokeAllFromDataset,
  visibilityTarget,
  onVisibilityTargetChange,
  selectedVisibilityDatasetIds,
  allVisibleVisibilityDatasetsSelected,
  onToggleVisibilityDataset,
  onToggleAllVisibilityDatasets,
  onBatchUpdateVisibility,
  grantUserSearchQuery,
  onGrantUserSearchChange,
  grantUserPage,
  grantUserPageSize,
  onGrantUserPageChange,
  onGrantUserPageSizeChange,
  grantUserTotal,
  loadingGrantUsers,
  grantUserItems,
  selectableGrantUsers,
  selectedGrantUserIds,
  validDatasetGrantUserIds,
  allVisibleUsersSelected,
  allMatchingUsersSelected,
  allMatchingUserCount,
  selectingAllUsers,
  onToggleGrantUser,
  onToggleAllUsers,
  onSelectAllMatchingUsers,
  onClearUserSelection,
  onGrantToDataset,
}: PermissionDatasetPanelProps) {
  const { t } = useTranslation();

  return (
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
                  onDatasetSearchChange(e.target.value);
                  onDatasetPageChange(1);
                }}
                placeholder={t("settings.permissionCenterModal.searchDatasets")}
                className="pl-9"
                disabled={submitting}
              />
            </div>
          </div>
          <div className="text-sm text-gray-500">
            {t("settings.permissionCenterModal.datasetCount", { count: datasetTotal })}
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
                  onVisibilityTargetChange(value as "public" | "private")
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
                onClick={onBatchUpdateVisibility}
                disabled={selectedVisibilityDatasetIds.length === 0 || submitting}
              >
                {t("settings.permissionCenterModal.applyToSelectedDatasets", {
                  count: selectedVisibilityDatasetIds.length,
                })}
              </Button>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              checked={allVisibleVisibilityDatasetsSelected}
              onCheckedChange={onToggleAllVisibilityDatasets}
            />
            <span className="text-sm text-gray-700">
              {t("settings.permissionCenterModal.selectVisibleDatasetsForVisibility", {
                count: pagedDatasets.length,
              })}
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
                      onClick={() => onSelectDatasetWithReset(dataset.dataset_id)}
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
                              isSelected ? "bg-white/20 text-white" : "bg-sky-100 text-sky-700",
                            )}
                          >
                            <Globe className="h-3 w-3" />
                            {t("settings.permissionCenterModal.publicDataset")}
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
                            {t("settings.permissionCenterModal.privateDataset")}
                          </span>
                        )}
                      </div>
                    </button>
                    <Checkbox
                      checked={selectedVisibilityDatasetIds.includes(dataset.dataset_id)}
                      onCheckedChange={(checked) =>
                        onToggleVisibilityDataset(dataset.dataset_id, checked)
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
            onPageChange={onDatasetPageChange}
            onPageSizeChange={(pageSize) => {
              onDatasetPageSizeChange(pageSize);
              onDatasetPageChange(1);
            }}
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
                  ? t("settings.permissionCenterModal.selectedDatasetName", {
                      name: selectedDataset.dataset_name,
                    })
                  : t("settings.permissionCenterModal.selectDatasetHint")}
              </p>
              {selectedDatasetIsPublic ? (
                <p className="mt-1 text-xs text-amber-700">
                  {t("settings.permissionCenterModal.publicDatasetGrantDisabled")}
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
              onClick={onRevokeAllFromDataset}
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
              {t("settings.permissionCenterModal.publicDatasetGrantDisabled")}
            </div>
          ) : sortedDatasetGrants.length === 0 ? (
            <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
              {t("settings.permissionCenterModal.noCurrentAccess")}
            </div>
          ) : (
            <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
              {sortedDatasetGrants.map((permission) => {
                const displayName =
                  permission.user_nickname || permission.user_email || permission.user_id;
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
                            {t(`settings.usersTab.role_${permission.user_role}`)}
                          </span>
                        )}
                        {typeof permission.user_is_active === "boolean" && (
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
                                date: new Date(permission.expires_at).toLocaleString(),
                              })
                            : t("settings.permissionModal.noExpiration")}
                        </span>
                        {!permission.is_valid && (
                          <span className="text-xs font-medium text-red-600">
                            {t("settings.permissionModal.expired")}
                          </span>
                        )}
                      </div>

                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => onRevokeFromDataset(permission)}
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
                  ? t("settings.permissionCenterModal.selectedDatasetName", {
                      name: selectedDataset.dataset_name,
                    })
                  : t("settings.permissionCenterModal.selectDatasetHint")}
              </p>
              {selectedDatasetIsPublic && (
                <p className="mt-1 text-xs text-amber-700">
                  {t("settings.permissionCenterModal.publicDatasetGrantDisabled")}
                </p>
              )}
            </div>
            <div className="text-xs text-gray-500">
              {t("settings.permissionCenterModal.userCount", { count: grantUserTotal })}
            </div>
          </div>
          <div className="relative mb-3">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
            <Input
              value={grantUserSearchQuery}
              onChange={(e) => {
                onGrantUserSearchChange(e.target.value);
                onGrantUserPageChange(1);
              }}
              placeholder={t("settings.permissionCenterModal.searchUsers")}
              className="pl-9"
              disabled={submitting || selectedDatasetIsPublic}
            />
          </div>
          <div className="mb-4 flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
            <Checkbox
              checked={allVisibleUsersSelected}
              onCheckedChange={onToggleAllUsers}
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
              allMatchingUsersSelected ? allMatchingUserCount : selectedGrantUserIds.length
            }
            selectingAll={selectingAllUsers}
            onSelectAllMatching={onSelectAllMatchingUsers}
            onClearSelection={onClearUserSelection}
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
                  const alreadyGranted = validDatasetGrantUserIds.has(user.id);
                  const isDatasetOwner =
                    selectedDataset?.user_id !== null && user.id === selectedDataset?.user_id;
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
                        onCheckedChange={(checked) => onToggleGrantUser(user.id, checked)}
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
                              {t("settings.permissionCenterModal.datasetOwner")}
                            </span>
                          )}
                          {!isDatasetOwner && alreadyGranted && (
                            <span className="inline-flex rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                              {t("settings.permissionCenterModal.alreadyGranted")}
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
              onPageChange={onGrantUserPageChange}
              onPageSizeChange={(pageSize) => {
                onGrantUserPageSizeChange(pageSize);
                onGrantUserPageChange(1);
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
                  disabled={submitting || !selectedDatasetId || selectedDatasetIsPublic}
                />
              </div>
              <div className="flex-1 text-xs text-gray-400">
                {t("settings.permissionModal.leaveEmptyForPermanent")}
              </div>
              <Button
                type="button"
                onClick={onGrantToDataset}
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
                  : t("settings.permissionCenterModal.grantSelectedUsers", {
                      count: selectedGrantUserIds.length,
                    })}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
