import React, { Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout/Layout';
import { Home } from './components/Home/Home';
import { ConversationView } from './components/ConversationView/ConversationView';

const DocsView = React.lazy(() => import('./components/DocsView').then(m => ({ default: m.DocsView })));
import { ConversationsProvider } from './contexts/ConversationsContext';
import { StreamStatusProvider } from './contexts/StreamStatusContext';
import { PreferencesProvider } from './contexts/PreferencesContext';
import { RequirementProvider } from './contexts/RequirementContext';
import './styles/global.css';

function ChatApp() {
  return (
    <PreferencesProvider>
      <StreamStatusProvider>
        <ConversationsProvider>
          <RequirementProvider>
            <Routes>
              <Route path="/" element={
                <Layout>
                  <Home />
                </Layout>
              } />
              <Route path="/c/:sessionId" element={
                <Layout>
                  <ConversationView />
                </Layout>
              } />
              <Route path="/docs" element={
                <Layout>
                  <Suspense fallback={
                    <div className="flex-1 flex items-center justify-center">
                      <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    </div>
                  }>
                    <DocsView />
                  </Suspense>
                </Layout>
              } />
            </Routes>
          </RequirementProvider>
        </ConversationsProvider>
      </StreamStatusProvider>
    </PreferencesProvider>
  );
}

export default ChatApp;
