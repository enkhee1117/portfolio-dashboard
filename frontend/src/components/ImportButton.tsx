"use client";
import { useState } from 'react';
import { useToast } from './Toast';
import { apiCall } from '../lib/api';

const FileConfig = {
    accept: ".xlsx, .xls, .csv",
    endpoint: "/api/import"
};

interface ImportButtonProps {
    onImportSuccess: () => void;
}

const ImportButton: React.FC<ImportButtonProps> = ({ onImportSuccess }) => {
    const [uploading, setUploading] = useState(false);
    const toast = useToast();

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files?.[0]) return;

        setUploading(true);
        const formData = new FormData();
        formData.append("file", e.target.files[0]);

        try {
            const res = await apiCall(FileConfig.endpoint, {
                method: "POST",
                body: formData,
            });

            if (res.ok) {
                const data = await res.json();
                toast.success(data.message || "Import successful!");
                onImportSuccess();
            } else {
                toast.error("Import failed.");
            }
        } catch (err) {
            console.error(err);
            toast.error("Error uploading file.");
        } finally {
            setUploading(false);
            e.target.value = "";
        }
    };

    return (
        <label className={`cursor-pointer inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-all ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}>
            {uploading ? (
                <>
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Importing...
                </>
            ) : (
                <>
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                    Import Excel
                </>
            )}
            <input
                type="file"
                className="hidden"
                accept={FileConfig.accept}
                onChange={handleFileUpload}
                disabled={uploading}
            />
        </label>
    );
};

export default ImportButton;
