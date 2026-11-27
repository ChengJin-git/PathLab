import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import "./page-loading.css";

export function DatasetLoading({
  header = true,
  files = false,
}: {
  header?: boolean;
  files?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="data-loading"
      role="status"
      aria-label={t("common.loading")}
      aria-busy="true"
      data-loading-layout={files ? "files" : "datasets"}
    >
      <span className="sr-only">{t("common.loading")}</span>
      <div aria-hidden="true">
        {header && (
          <div className="data-loading-header">
            <div>
              <div className="loading-shape loading-title" />
              <div className="loading-shape loading-subtitle" />
            </div>
            <div className="loading-shape loading-action" />
          </div>
        )}
        <div className="data-loading-search loading-shape" />
        <div className="data-loading-filters">
          <span className="loading-shape" />
          <span className="loading-shape" />
          <span className="loading-shape" />
        </div>
        {files ? (
          <div className="data-loading-table">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index}>
                <span className="loading-shape" />
                <span className="loading-shape" />
                <span className="loading-shape" />
              </div>
            ))}
          </div>
        ) : (
          <div className="data-loading-grid">
            {Array.from({ length: 8 }, (_, index) => (
              <div className="data-loading-card" key={index}>
                <div className="loading-shape loading-card-icon" />
                <div className="loading-shape loading-card-name" />
                <div className="loading-shape loading-card-detail" />
                <div className="loading-card-footer">
                  <span className="loading-shape" />
                  <span className="loading-shape" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PageLoading({
  fullPage = false,
}: {
  fullPage?: boolean;
}) {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  return (
    <div className={fullPage ? "page-loading-full" : "page-loading-content"}>
      {pathname === "/datasets" ? (
        <DatasetLoading />
      ) : pathname === "/upload" ? (
        <div
          className="data-loading upload-loading"
          role="status"
          aria-label={t("common.loading")}
          aria-busy="true"
        >
          <span className="sr-only">{t("common.loading")}</span>
          <div aria-hidden="true">
            <div className="data-loading-header">
              <div>
                <div className="loading-shape loading-title" />
                <div className="loading-shape loading-subtitle" />
              </div>
            </div>
            <div className="upload-loading-form">
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index}>
                  <div className="loading-shape loading-field-label" />
                  <div className="loading-shape loading-field" />
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div
          role="status"
          aria-label={t("common.loading")}
          className="page-loading-indicator"
        >
          <span className="page-loading-orbit" aria-hidden="true" />
          <span className="sr-only">{t("common.loading")}</span>
        </div>
      )}
    </div>
  );
}
