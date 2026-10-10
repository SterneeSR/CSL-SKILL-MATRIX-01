import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Register } from './Register';
import { Login } from './Login';
import { Pending } from './Pending';
import { Rejected } from './Rejected';
import { Welcome } from './Welcome';
import { api } from './api';
import { ProtectedRoute } from './routes/ProtectedRoute';
import { StudentLayout } from './layouts/StudentLayout';
import { StudentDashboardPage } from './pages/student/StudentDashboardPage';
import { StudentProfilePage } from './pages/student/StudentProfilePage';
import { StudentSkillsPage } from './pages/student/StudentSkillsPage';
import { StudentActivitiesPage } from './pages/student/StudentActivitiesPage';
import { StudentActivityDetailPage } from './pages/student/StudentActivityDetailPage';
import { ComingSoonPage } from './pages/student/ComingSoonPage';
import { StaffActivitiesPage } from './pages/staff/StaffActivitiesPage';

interface UserData {
  email: string;
  name: string;
  role?: string;
  status?: string;
}

/** Reusable placeholder for not-yet-implemented student modules. */
function ComingSoon({ module }: { module: string }) {
  return <ComingSoonPage module={module} />;
}

export default function App() {
  const [user, setUser] = useState<UserData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if session is already authenticated
    api.get('/me/')
      .then((res) => {
        if (res.data && res.data.email) {
          setUser(res.data);
        }
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const handleLogout = () => {
    setUser(null);
  };

  if (loading) {
    return <div style={{ textAlign: 'center', marginTop: 50 }}>Loading...</div>;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to={user ? '/welcome' : '/login'} replace />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/login"
          element={
            user ? <Navigate to={user.role === 'STUDENT' ? '/student' : '/welcome'} replace /> : <Login onLoginSuccess={(u) => setUser(u)} />
          }
        />
        <Route path="/pending" element={<Pending />} />
        <Route path="/rejected" element={<Rejected />} />
        <Route
          path="/welcome"
          element={
            user ? (
              <Welcome user={user} onLogout={handleLogout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="/staff/activities"
          element={
            user && user.role !== 'STUDENT' ? (
              <StaffActivitiesPage />
            ) : (
              <Navigate to="/welcome" replace />
            )
          }
        />

        {/* Authenticated student section */}
        <Route
          path="/student"
          element={
            <ProtectedRoute isAuthenticated={!!user}>
              <StudentLayout onLogout={handleLogout} />
            </ProtectedRoute>
          }
        >
          <Route index element={<StudentDashboardPage />} />
          <Route path="profile" element={<StudentProfilePage />} />
          <Route path="skills" element={<StudentSkillsPage />} />
          <Route path="activities" element={<StudentActivitiesPage />} />
          <Route path="activities/:id" element={<StudentActivityDetailPage />} />
          <Route path="performance" element={<ComingSoon module="Performance" />} />
          <Route path="leaderboard" element={<ComingSoon module="Leaderboard" />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
