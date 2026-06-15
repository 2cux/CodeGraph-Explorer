import { listUsers } from "./handlers";
import { UserCard } from "./UserCard";

export function ActionPanel() {
  return (
    <button onClick={listUsers}>
      <UserCard />
    </button>
  );
}
