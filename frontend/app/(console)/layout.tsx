import { AppShell } from "@/components/shell/AppShell";

/** Every console screen: the simulation notice, the header, the navigation and the sign-in gate. */
export default function ConsoleLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
