import { Link } from "react-router-dom";

export function Logo() {
  return (
    <Link
      className="opacity-70 transition-opacity duration-300 hover:opacity-100 text-sm font-medium"
      to="/deep-research"
    >
      PathLab Research
    </Link>
  );
}
