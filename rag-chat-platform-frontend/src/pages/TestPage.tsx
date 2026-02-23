import { useState } from "react";

type TestResult = {
  question: string;
  round1_ans: string;
  round1_pass: boolean;
  round1_score: number;
  round1_reason: string;
  round2_ans: string;
  round2_pass: boolean | null;
  round2_score: number;
  final_ans: string;
};

export default function TestPage() {
  const [inputs, setInputs] = useState("");
  const [language, setLanguage] = useState("Python");
  const [results, setResults] = useState<TestResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState(0);

  const runTests = async () => {
    const questions = inputs.split("\n").map(q => q.trim()).filter(q => q.length > 0);
    if (questions.length === 0) {
      alert("질문을 입력하세요.");
      return;
    }
    setIsLoading(true);
    setResults([]);
    setProgress(0);
    
    const newResults: TestResult[] = [];
    for (let i = 0; i < questions.length; i++) {
      try {
        const res = await fetch("/api/test/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // style을 Expert로 고정하여 테스트 진행
          body: JSON.stringify({ question: questions[i], language, style: "Expert" }),
        });
        
        if (!res.ok) throw new Error("SERVER ERROR");
        const data = await res.json();
        
        newResults.push(data);
        setResults([...newResults]);
      } catch (e) {
        newResults.push({
          question: questions[i],
          round1_ans: "ERROR",
          round1_pass: false,
          round1_score: 0,
          round1_reason: "API FAIL",
          round2_ans: "-",
          round2_pass: null,
          round2_score: 0,
          final_ans: "ERROR"
        });
        setResults([...newResults]);
      }
      setProgress(Math.round(((i + 1) / questions.length) * 100));
    }
    setIsLoading(false);
  };

  const downloadCSV = () => {
    if (results.length === 0) return;
    const headers = ["Question", "Lang", "R1 Result", "R1 Score", "R1 Reason", "R2 Result", "R2 Score", "Final"];
    const rows = results.map(r => [
      `"${r.question.replace(/"/g, '""')}"`,
      language,
      r.round1_pass ? "PASS" : "FAIL",
      r.round1_score,
      `"${r.round1_reason.replace(/"/g, '""')}"`,
      r.round2_pass === null ? "-" : (r.round2_pass ? "PASS" : "FAIL"),
      r.round2_score,
      `"${r.final_ans.replace(/"/g, '""')}"`
    ]);
    const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `test_results_${new Date().getTime()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-8 max-w-7xl mx-auto h-screen flex flex-col bg-white text-slate-900 font-sans">
      <header className="flex justify-between items-center mb-8">
        <h1 className="text-xl font-bold tracking-tight">EVALUATION SYSTEM</h1>
        {/* 기존의 파일 업로드 및 URL Fetch UI 제거됨 */}
      </header>

      <div className="grid grid-cols-4 gap-6 mb-8">
        <div className="col-span-3">
          <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
            Test Questions (Line Separated)
          </label>
          <textarea 
            className="w-full h-32 p-4 border border-slate-200 rounded-xl text-sm outline-none focus:border-indigo-500 transition-all bg-slate-50"
            value={inputs}
            onChange={(e) => setInputs(e.target.value)}
            placeholder="ENTER QUESTIONS..."
          />
        </div>
        <div className="flex flex-col justify-end gap-3">
          <div>
            <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Target Language</label>
            <select className="w-full p-2.5 border border-slate-200 rounded-lg text-sm bg-white outline-none" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {/* V2 파이프라인 언어 목록에 맞게 유지 */}
              {["Python", "Java", "JavaScript", "C#"].map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <button 
            onClick={runTests} 
            disabled={isLoading} 
            className={`w-full py-3 rounded-lg font-bold text-white transition-all shadow-sm ${isLoading ? "bg-slate-300" : "bg-indigo-600 hover:bg-indigo-700"}`}
          >
            {isLoading ? `RUNNING (${progress}%)` : "RUN TEST"}
          </button>
          {results.length > 0 && !isLoading && (
            <button onClick={downloadCSV} className="w-full py-2.5 border border-indigo-600 text-indigo-600 rounded-lg font-bold text-xs hover:bg-indigo-50 transition-all">
              DOWNLOAD CSV
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto border border-slate-200 rounded-xl shadow-sm bg-white">
        <table className="w-full text-xs text-left border-collapse">
          <thead className="bg-slate-50 text-slate-500 sticky top-0 border-b border-slate-200">
            <tr>
              <th className="p-4 font-bold uppercase tracking-wider">No</th>
              <th className="p-4 font-bold uppercase tracking-wider w-1/4">Question</th>
              <th className="p-4 font-bold uppercase tracking-wider text-center">R1</th>
              <th className="p-4 font-bold uppercase tracking-wider w-1/4">Evaluation Reason</th>
              <th className="p-4 font-bold uppercase tracking-wider text-center">R2</th>
              <th className="p-4 font-bold uppercase tracking-wider w-1/3">Final Answer</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {results.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50 transition-colors">
                <td className="p-4 text-slate-400">{i + 1}</td>
                <td className="p-4 font-medium text-slate-800">{r.question}</td>
                <td className="p-4 text-center">
                  <span className={`px-2 py-1 rounded text-[10px] font-black ${r.round1_pass ? "text-indigo-600 bg-indigo-50" : "text-red-600 bg-red-50"}`}>
                    {r.round1_pass ? "PASS" : "FAIL"}
                  </span>
                  <div className="text-[9px] text-slate-400 mt-1">{r.round1_score}/10</div>
                </td>
                <td className="p-4 text-slate-500 leading-relaxed">{r.round1_reason}</td>
                <td className="p-4 text-center">
                  {r.round2_pass === null ? <span className="text-slate-200">-</span> : (
                    <>
                      <span className={`px-2 py-1 rounded text-[10px] font-black ${r.round2_pass ? "text-indigo-600 bg-indigo-50" : "text-red-600 bg-red-50"}`}>
                        {r.round2_pass ? "PASS" : "FAIL"}
                      </span>
                      <div className="text-[9px] text-slate-400 mt-1">{r.round2_score}/10</div>
                    </>
                  )}
                </td>
                <td className="p-4 text-slate-400 leading-normal truncate max-w-xs" title={r.final_ans}>
                  {r.final_ans}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {results.length === 0 && !isLoading && (
          <div className="p-20 text-center text-slate-300 font-bold uppercase tracking-widest text-xs">
            No data available. Run test to begin.
          </div>
        )}
      </div>
    </div>
  );
}