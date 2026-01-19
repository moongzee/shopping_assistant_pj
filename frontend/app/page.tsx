import Link from "next/link";
import ChatClient from "@/components/ChatClient";

export default function Page() {
  return (
    <>
      <div className="topbar">
        <div className="topbarSide">Fashion</div>
        <div className="topbarBrand">
          <span>Shopping assistant</span>
          <span className="beta">beta</span>
        </div>
        <Link className="topbarButton" href="/admin">
          학습/최적화 대시보드 →
        </Link>
      </div>
      <ChatClient />
    </>
  );
}

