import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout/Layout';
import { Home } from './components/Home/Home';
import { ConversationView } from './components/ConversationView/ConversationView';
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
            </Routes>
          </RequirementProvider>
        </ConversationsProvider>
      </StreamStatusProvider>
    </PreferencesProvider>
  );
}

export default ChatApp;
