import { ArrowLeft, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useUploadText } from "./uploadText";

export function UploadHeader({
  step,
  onBack,
  onSetup,
  append = false,
}: {
  step: 1 | 2;
  onBack: () => void;
  onSetup?: () => void;
  append?: boolean;
}) {
  const copy = useUploadText();
  const { t } = useTranslation();
  return (
    <header className="upload-header">
      <div className="upload-header-heading">
        <div>
          <h1>{copy(append ? "appendTitle" : "title")}</h1>
          <p>
            {copy(
              append
                ? "appendSubtitle"
                : step === 1
                  ? "subtitle"
                  : "filesSubtitle",
            )}
          </p>
        </div>
        <button type="button" onClick={onBack} className="upload-back">
          <ArrowLeft size={15} />
          {t("common.back")}
        </button>
      </div>
      <nav aria-label={copy("steps")} className="upload-steps">
        <ol>
          {[1, 2].map((value) => (
            <li
              key={value}
              aria-current={step === value ? "step" : undefined}
              data-complete={step > value}
            >
              {value === 1 && onSetup ? (
                <button type="button" onClick={onSetup}>
                  <span className="upload-step-number">
                    <Check size={13} />
                  </span>
                  {copy("setup")}
                </button>
              ) : (
                <span className="upload-step-label">
                  <span className="upload-step-number">{value}</span>
                  {copy(value === 1 ? "setup" : "addFiles")}
                </span>
              )}
            </li>
          ))}
        </ol>
        <span className="upload-step-position">
          {String(step).padStart(2, "0")} <span>/ 02</span>
        </span>
      </nav>
    </header>
  );
}
