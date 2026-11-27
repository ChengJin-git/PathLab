import { useNavigate, useSearchParams } from "react-router-dom";
import GeneratePredictions from "../components/results/workbench/GeneratePredictions";
import { useAuth } from "../contexts/AuthContext";
import { getWorkspaceSelection } from "../lib/workspaceSelection";

export default function EvaluationPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user } = useAuth();
  return (
    <GeneratePredictions
      scopeKey={`${user?.id}:${getWorkspaceSelection().workspaceId || "all"}`}
      initialMode={params.get("mode") || "external"}
      modelId={params.get("model") || ""}
      onClose={() => navigate("/tools")}
    />
  );
}
