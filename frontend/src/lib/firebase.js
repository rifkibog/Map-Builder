import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';

const firebaseConfig = {
  apiKey: "AIzaSyDDR5N0-m2omuS-Y7qM7gU1oUe9mrrcOgc",
  authDomain: "telkomsel-homepass-6536d.firebaseapp.com",
  projectId: "telkomsel-homepass-6536d",
  storageBucket: "telkomsel-homepass-6536d.firebasestorage.app",
  messagingSenderId: "822357572980",
  appId: "1:822357572980:web:39c7050c6df63315da0021",
  measurementId: "G-ZF6SEDKSR5"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();

// Force account selection setiap login
googleProvider.setCustomParameters({
  prompt: 'select_account'
});
