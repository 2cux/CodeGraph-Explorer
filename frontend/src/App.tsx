import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<div>Project Overview</div>} />
          <Route path="/search" element={<div>Symbol Search</div>} />
          <Route path="/symbol/:nodeId" element={<div>Symbol Detail</div>} />
          <Route path="/graph" element={<div>Graph Explorer</div>} />
          <Route path="/impact" element={<div>Impact View</div>} />
          <Route path="/context" element={<div>Context Pack Viewer</div>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
