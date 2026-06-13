import { useTranslation } from "react-i18next";

export interface BulkSelectionBannerProps {
  allPageSelected: boolean;
  allMatchingSelected: boolean;
  pageCount: number;
  selectedCount: number;
  selectingAll?: boolean;
  onSelectAllMatching: () => void;
  onClearSelection: () => void;
}

export function BulkSelectionBanner({
  allPageSelected,
  allMatchingSelected,
  pageCount,
  selectedCount,
  selectingAll,
  onSelectAllMatching,
  onClearSelection,
}: BulkSelectionBannerProps) {
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
