import React from "react";
import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { InstitutionsPage } from "./pages/InstitutionsPage";
import { InstitutionPage } from "./pages/InstitutionPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <InstitutionsPage /> },
      { path: "institutions/:institutionId", element: <InstitutionPage /> },
      { path: "*", element: <NotFoundPage /> }
    ]
  }
]);


