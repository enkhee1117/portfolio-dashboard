"use client";
import { useState } from 'react';
import { Trade } from '../app/types';

interface ManualTradeFormProps {
    onTradeAdded: () => void;
}

const ManualTradeForm: React.FC<ManualTradeFormProps> = ({ onTradeAdded }) => {
    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        ticker: '',
        type: 'Equity',
        side: 'Buy',
        price: '',
        quantity: '',
        currency: 'USD'
    });
    const [loading, setLoading] = useState(false);

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        try {
            let res = await fetch("/api/trades/manual", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ...formData,
                    price: parseFloat(formData.price),
                    quantity: parseFloat(formData.quantity)
                })
            });

            if (res.status === 409) {
                // Duplicate detected
                if (confirm("This looks like a duplicate trade. Add it anyway?")) {
                    // Retry with force=true
                    res = await fetch("/api/trades/manual?force=true", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            ...formData,
                            price: parseFloat(formData.price),
                            quantity: parseFloat(formData.quantity)
                        })
                    });
                } else {
                    setLoading(false);
                    return;
                }
            }

            if (res.ok) {
                alert("Trade added successfully!");
                onTradeAdded();
                setFormData({ ...formData, ticker: '', price: '', quantity: '' });
            } else {
                alert("Failed to add trade.");
            }
        } catch (err) {
            console.error(err);
            alert("Error adding trade.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="p-4 bg-gray-800 rounded-lg shadow-md mb-6 border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-4">Add Manual Trade</h3>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <input type="date" name="date" value={formData.date} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded" required />
                <input type="text" name="ticker" placeholder="Ticker" value={formData.ticker} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded uppercase" required />
                <select name="side" value={formData.side} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded">
                    <option value="Buy">Buy</option>
                    <option value="Sell">Sell</option>
                </select>
                <select name="type" value={formData.type} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded">
                    <option value="Equity">Equity</option>
                    <option value="Option">Option</option>
                </select>
                <input type="number" step="0.01" name="quantity" placeholder="Quantity" value={formData.quantity} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded" required />
                <input type="number" step="0.01" name="price" placeholder="Price" value={formData.price} onChange={handleChange} className="bg-gray-700 text-white p-2 rounded" required />
            </div>
            <button type="submit" disabled={loading} className="mt-4 w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded font-medium transition-colors">
                {loading ? "Adding..." : "Add Trade"}
            </button>
        </form>
    );
};

export default ManualTradeForm;
