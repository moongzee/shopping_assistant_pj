import Link from "next/link";
import ChatClientClassic from "@/components/ChatClientClassic";

export default function Page() {
  return (
    <div className="classic-theme">
      <div className="container">
        <div className="header">
          <div className="brand">
            <h1>Shopping Assistant Demo</h1>
            <span className="pill">LangGraph 진행상태 + 스트리밍 + 상품 카드</span>
          </div>
          <Link className="pill" href="/admin">
            학습/최적화 대시보드 →
          </Link>
        </div>
        <ChatClientClassic />
      </div>
    </div>
  );
}
