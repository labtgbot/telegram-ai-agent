import { redirect } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { getAdminSession } from "@/lib/auth/session";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getAdminSession();
  if (!session) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Topbar role={session.role} sub={session.sub} />
        <main className="flex-1 overflow-y-auto bg-slate-50 p-8 dark:bg-slate-900">{children}</main>
      </div>
    </div>
  );
}
