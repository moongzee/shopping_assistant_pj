import Link from "next/link";
import ChatClient from "@/components/ChatClient";

export default function Page() {
  return (
    <div className="gpt-theme">
      <div className="header">
        <div className="brand">
          <h1>Shopping Assistant Demo</h1>
          <span className="pill">LangGraph 진행상태 + 스트리밍 + 상품 카드</span>
        </div>
        <Link className="pill" href="/admin">
          학습/최적화 대시보드 →
        </Link>
      </div>
      <ChatClient />
      <footer className="footer">
        <span className="footerText">© 2026 AI Commerce Assistant. All rights reserved.</span>
      </footer>
    </div>
  );
}
