import type { ComponentProps } from "react";
import ConfirmDialog from "./ConfirmDialog";

type Props = Omit<ComponentProps<typeof ConfirmDialog>, "danger">;

export default function DangerConfirmDialog(props: Props) {
  return <ConfirmDialog {...props} danger />;
}
