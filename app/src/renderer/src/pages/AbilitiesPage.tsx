import { useNavigate } from "react-router-dom";
import CapabilityLibrary from "../components/chat/CapabilityLibrary";
import { useAuth } from "../contexts/AuthContext";
export default function AbilitiesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const target = () =>
    sessionStorage.getItem("workbench:chat:" + user?.id) || "/dashboard";
  return (
    <CapabilityLibrary
      inline
      kind="skill"
      onClose={() => navigate(target())}
      onUse={(command) => {
        sessionStorage.setItem(
          "workbench:pending-skill:" + user?.id,
          JSON.stringify(command),
        );
        navigate(target());
      }}
    />
  );
}
