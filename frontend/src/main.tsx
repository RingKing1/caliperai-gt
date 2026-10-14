import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './queryClient';
import App from './App';
import { AuthenticatedActivityTracker } from './providers/AuthenticatedActivityTracker';
import { UploadProvider } from './providers/UploadProvider';
import { FloatingUploadProgress } from './components/FloatingUploadProgress';
import { BRAND } from './config/branding';
import './index.css';

document.title = `${BRAND.name}: Sensor Fusion Annotation Platform`;


ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <UploadProvider>
          <AuthenticatedActivityTracker>
            <App />
          </AuthenticatedActivityTracker>
          <FloatingUploadProgress />
        </UploadProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
